#!/usr/bin/env python3
"""Kemper (Key Mapper): press a key combo (e.g. Alt+2), get a character or text (e.g. ²) typed in any app.

Runs on Windows, macOS and Linux (X11). One file. Run it to open the window, or see every command with:
    python kemper.pyw --help
https://kemper.talken.in  ·  https://github.com/Shashwat-Gupta57/Kemper  ·  MIT License
"""
import argparse, base64, ctypes, json, os, plistlib, re, shutil, socket, struct, subprocess, sys, threading, time, webbrowser

IS_WIN, IS_MAC = sys.platform == "win32", sys.platform == "darwin"
IS_LINUX = not (IS_WIN or IS_MAC)
OS_NAME = "Windows" if IS_WIN else "macOS" if IS_MAC else "Linux"
if IS_WIN:
    import winreg
    from ctypes import wintypes

APP = "Kemper"
VERSION = "3.2.0"
MARKETPLACE_URL = "https://kemper.talken.in/#marketplace"

def config_dir():
    """Where settings live: KEMPER_HOME if set (the tests use it), else each system's usual place."""
    if os.environ.get("KEMPER_HOME"):
        return os.environ["KEMPER_HOME"]
    if IS_WIN:
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP)
    if IS_MAC:
        return os.path.expanduser("~/Library/Application Support/Kemper")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "kemper")

CONFIG = os.path.join(config_dir(), "mappings.json")
EDITOR_TITLE = "Kemper Keypack Editor"
KEYPACK_EXT = ".kmppck"
KEYPACK_PROGID = "Kemper.Keypack"
KEYPACK_MAX_BYTES = 1_000_000  # keypacks come from other people: keep what we read bounded
KEYPACK_MAX_ITEMS = 1000
TEXT_MAX = 10_000
PICKER_TITLE = "Kemper Picker"
PICKER_ID = 0xB000  # hotkey id of the quick picker; shortcut ids are 1..n
DEFAULT_PICKER = {"enabled": True, "mods": ["Ctrl", "Alt"], "vk": 0x4B, "key": "K"}
PORT = 47321  # single-instance socket; a second launch just tells the first to show its window
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"  # Windows only


# name, virtual key, RegisterHotKey flag
MODS = [("Ctrl", 0x11, 0x2), ("Alt", 0x12, 0x1), ("Shift", 0x10, 0x4), ("Win", 0x5B, 0x8)]
MOD_NOREPEAT, WM_HOTKEY, WM_QUIT = 0x4000, 0x0312, 0x0012
KEYUP, UNICODE = 0x2, 0x4

def utf16_units(text):
    b = text.encode("utf-16-le")
    return [int.from_bytes(b[i:i + 2], "little") for i in range(0, len(b), 2)]

# ---------- Windows: hotkeys, typing and system integration through Win32 ----------
if IS_WIN:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32")

    # ---------- Win32 input ----------
    ULONG_PTR = ctypes.c_size_t
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]
    class MOUSEINPUT(ctypes.Structure):  # only here so the union has the right size
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]
    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)

    def _key(vk=0, scan=0, flags=0):
        return INPUT(type=1, u=_U(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))

    def _send(inputs):
        arr = (INPUT * len(inputs))(*inputs)
        user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))

    def down(vk):
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    def type_text(text):
        # Tap an unassigned key so a lone Alt/Win release doesn't open the app's menu / Start (same trick AutoHotkey uses).
        _send([_key(0xE8), _key(0xE8, flags=KEYUP)])
        end = time.time() + 2
        while any(down(vk) for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C)) and time.time() < end:
            time.sleep(0.01)  # held modifiers would turn our typed chars into shortcuts
        inputs = []
        for ch in text.replace("\r\n", "\n"):
            if ch == "\n":
                inputs += [_key(0x0D), _key(0x0D, flags=KEYUP)]
            else:
                for u in utf16_units(ch):
                    inputs += [_key(scan=u, flags=UNICODE), _key(scan=u, flags=UNICODE | KEYUP)]
        if inputs:
            _send(inputs)

    def key_name(vk):
        sc = user32.MapVirtualKeyW(vk, 0)
        if vk in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E):
            sc |= 0x100  # extended keys, otherwise they read as numpad keys
        buf = ctypes.create_unicode_buffer(32)
        return buf.value if user32.GetKeyNameTextW(sc << 16, buf, 32) else f"Key {vk}"

    class Listener(threading.Thread):
        """Owns the global hotkeys. RegisterHotKey ties them to this thread's message queue."""
        def __init__(self, rows, on_fire=None, picker=None, on_picker=None):
            super().__init__(daemon=True)
            self.rows, self.on_fire, self.failed, self.ready = rows, on_fire, [], threading.Event()
            self.picker, self.on_picker = picker, on_picker

        def run(self):
            self.tid = kernel32.GetCurrentThreadId()
            swallowed = input_language_hotkeys()
            for i, m in enumerate(self.rows):
                if not user32.RegisterHotKey(None, i + 1, hotkey_flags(m), m["vk"]):
                    self.failed.append(combo_label(m))
                elif combo_id(m) in swallowed:  # registers fine, but Windows' text input eats the keys first
                    self.failed.append(combo_label(m) + " (Windows uses it to switch keyboard language)")
            if self.picker and not user32.RegisterHotKey(None, PICKER_ID, hotkey_flags(self.picker), self.picker["vk"]):
                self.failed.append(combo_label(self.picker) + " (quick picker)")
            elif self.picker and combo_id(self.picker) in swallowed:
                self.failed.append(combo_label(self.picker) + " (quick picker; Windows uses it to switch keyboard language)")
            self.ready.set()
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == PICKER_ID and self.on_picker:
                    # own thread: opening the popup waits on the UI thread, which may be waiting on us
                    threading.Thread(target=self.on_picker, daemon=True).start()
                elif msg.message == WM_HOTKEY and 0 < msg.wParam <= len(self.rows):
                    m = self.rows[msg.wParam - 1]
                    type_text(m["text"])
                    if self.on_fire:
                        self.on_fire(m)
            for i in range(len(self.rows)):
                user32.UnregisterHotKey(None, i + 1)
            user32.UnregisterHotKey(None, PICKER_ID)

        def stop(self):
            user32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)
            self.join(2)

    # start with Windows
    def startup_cmd():
        return f'"{pythonw()}" "{os.path.abspath(__file__)}" --hidden'

    def startup_value():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                return winreg.QueryValueEx(k, APP)[0]
        except OSError:
            return None

    def set_startup(on):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, startup_cmd())
            else:
                try:
                    winreg.DeleteValue(k, APP)
                except FileNotFoundError:
                    pass

    # desktop shortcut and .kmppck files
    def desktop_path():
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)  # CSIDL_DESKTOPDIRECTORY, follows OneDrive moves
        return os.path.join(buf.value, f"{APP}.lnk")

    def desktop_enabled():
        return os.path.exists(desktop_path())

    def make_shortcut(lnk):
        """A .pyw file always shows Python's icon, so Kemper's own icon lives on a shortcut to it."""
        me = os.path.abspath(__file__)
        env = {**os.environ, "K_LNK": lnk, "K_EXE": pythonw(), "K_ARGS": f'"{me}"', "K_ICON": icon_path(), "K_DIR": os.path.dirname(me)}
        ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:K_LNK); $s.TargetPath = $env:K_EXE; "
              "$s.Arguments = $env:K_ARGS; $s.IconLocation = $env:K_ICON; $s.WorkingDirectory = $env:K_DIR; "
              "$s.Description = 'Kemper (Key Mapper)'; $s.Save()")  # paths go in via env vars, never pasted into the script
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env,
                           capture_output=True, creationflags=0x08000000)  # CREATE_NO_WINDOW
        if r.returncode or not os.path.exists(lnk):
            raise OSError(r.stderr.decode(errors="replace").strip() or "couldn't create the shortcut")

    def set_desktop(on):
        lnk = desktop_path()
        if on:
            make_shortcut(lnk)
        elif os.path.exists(lnk):
            os.remove(lnk)

    # Start menu: what makes typing "Kemper" in Start (Windows search) find it
    def app_menu_path():
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x02, None, 0, buf)  # CSIDL_PROGRAMS: this user's Start menu
        return os.path.join(buf.value, f"{APP}.lnk")

    def app_menu_registered():
        """True when Kemper is in the Start menu and the entry still points at this file (it may have moved)."""
        try:
            with open(app_menu_path(), "rb") as f:
                return f'"{os.path.abspath(__file__)}"'.encode("utf-16-le") in f.read()  # .lnk keeps its arguments in UTF-16
        except OSError:
            return False

    def register_app_menu():
        if not app_menu_registered():
            make_shortcut(app_menu_path())

    def unregister_app_menu():
        if os.path.exists(app_menu_path()):
            os.remove(app_menu_path())

    def keypack_cmd():
        return f'"{pythonw()}" "{os.path.abspath(__file__)}" --keypack "%1"'

    def keypack_keys():
        base = r"Software\Classes"
        return {rf"{base}\{KEYPACK_EXT}": KEYPACK_PROGID, rf"{base}\{KEYPACK_PROGID}": "Kemper Keypack",
                rf"{base}\{KEYPACK_PROGID}\DefaultIcon": icon_path(), rf"{base}\{KEYPACK_PROGID}\shell\open\command": keypack_cmd()}

    def keypacks_registered():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{KEYPACK_PROGID}\shell\open\command") as k:
                return winreg.QueryValueEx(k, "")[0] == keypack_cmd()
        except OSError:
            return False

    def register_keypacks():
        """Make .kmppck files open in Kemper, with Kemper's icon. Current user only, no admin; redone if Kemper moved."""
        changed = False
        for key, value in keypack_keys().items():
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                    if winreg.QueryValueEx(k, "")[0] == value:
                        continue
            except OSError:
                pass
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, value)
            changed = True
        if changed:
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED: refresh icons

    def delete_key_tree(path):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                subs = []
                while True:
                    try:
                        subs.append(winreg.EnumKey(k, len(subs)))
                    except OSError:
                        break
            for sub in subs:
                delete_key_tree(path + "\\" + sub)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            pass

    def unregister_keypacks():
        delete_key_tree(rf"Software\Classes\{KEYPACK_EXT}")
        delete_key_tree(rf"Software\Classes\{KEYPACK_PROGID}")
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)

    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)

    def set_clipboard(text):
        """Put text on the Windows clipboard. Returns False if another app is holding the clipboard."""
        data = text.encode("utf-16-le") + b"\0\0"
        for _ in range(10):  # another app may have it open for a moment
            if user32.OpenClipboard(None):
                break
            time.sleep(0.05)
        else:
            return False
        try:
            user32.EmptyClipboard()
            h = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
            p = kernel32.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            kernel32.GlobalUnlock(h)
            return bool(user32.SetClipboardData(13, h))  # CF_UNICODETEXT; Windows owns the memory now
        finally:
            user32.CloseClipboard()

    def documents_folder():
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # CSIDL_PERSONAL
        return buf.value or os.path.expanduser("~")

    # windows on screen
    def os_is_dark():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except OSError:
            return False

    user32.FindWindowExW.restype = wintypes.HWND

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
    user32.MonitorFromPoint.restype = wintypes.HANDLE

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    def own_window(title=APP):
        """Our top-level window. Matches by process too, since e.g. an Explorer folder can also be titled 'Kemper'."""
        hwnd = None
        while hwnd := user32.FindWindowExW(None, hwnd, None, title):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == os.getpid():
                return hwnd

    def dark_title_bar(dark, title=APP):
        hwnd = own_window(title)
        if hwnd:
            val = ctypes.c_int(1 if dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), 4)  # DWMWA_USE_IMMERSIVE_DARK_MODE
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x27)  # SWP_FRAMECHANGED|NOMOVE|NOSIZE|NOZORDER: repaint the title bar

    def place_popup(hwnd):
        """Style the picker as a popup (no taskbar button, round corners) and put it by the mouse, on screen."""
        ex = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        user32.SetWindowLongW(hwnd, -20, (ex | 0x80) & ~0x40000)  # +WS_EX_TOOLWINDOW, -WS_EX_APPWINDOW
        round_ = ctypes.c_int(2)  # DWMWCP_ROUND, Windows 11 only; ignored elsewhere
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(round_), 4)
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        user32.GetMonitorInfoW(user32.MonitorFromPoint(pt, 2), ctypes.byref(mi))  # MONITOR_DEFAULTTONEAREST
        wa = mi.rcWork
        x = min(max(pt.x - w // 2, wa.left), wa.right - w)
        y = min(max(pt.y - 40, wa.top), wa.bottom - h)
        user32.SetWindowPos(hwnd, -1, x, y, 0, 0, 0x11)  # HWND_TOPMOST, SWP_NOSIZE|SWP_NOACTIVATE


    CAN_DESKTOP = CAN_KEYPACK_FILES = CAN_APP_MENU = True

    user32.VkKeyScanW.argtypes = (wintypes.WCHAR,)  # without this ctypes passes a pointer, not the char
    user32.VkKeyScanW.restype = ctypes.c_short

    def vk_for_char(ch):
        """The key that types ch on this keyboard layout: (vk, needs a modifier), or None."""
        r = user32.VkKeyScanW(ch)
        return None if r == -1 else (r & 0xFF, bool(r >> 8))

    def pythonw():
        return sys.executable.replace("python.exe", "pythonw.exe")

    def active_app():
        return user32.GetForegroundWindow()

    def activate(app):
        if app:
            user32.SetForegroundWindow(app)

    def show_popup(window, title):
        hwnd = own_window(title)
        if hwnd:
            place_popup(hwnd)
        window.show()
        if hwnd:
            user32.SetForegroundWindow(hwnd)  # allowed: we just received the hotkey

    def bring_to_front(title=APP):
        hwnd = own_window(title)
        if hwnd:
            user32.SetForegroundWindow(hwnd)

    def allow_foreground():
        user32.AllowSetForegroundWindow(-1)  # we were just clicked, so the running Kemper may come to the front

    def app_identity():
        # own taskbar identity, so Windows shows Kemper's icon instead of grouping it under Python
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Kemper.KeyMapper")

    def alert(msg):
        user32.MessageBoxW(None, msg, APP, 0x10)

    def show_file(path):
        subprocess.Popen(f'explorer /select,"{path}"')

    def webview2_version():
        guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        for root, path in ((winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"),
                           (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{guid}")):
            try:
                with winreg.OpenKey(root, path) as k:
                    v = winreg.QueryValueEx(k, "pv")[0]
                    if v and v != "0.0.0.0":
                        return v
            except OSError:
                pass

    def platform_checks(check):
        wv2 = webview2_version()
        check(0 if wv2 else 1, f"Edge WebView2 {wv2} (draws the window)" if wv2 else
              "Edge WebView2 not found, so the window may not open. Get it from https://go.microsoft.com/fwlink/p/?LinkId=2124703")

    def input_language_hotkeys():
        """Combos Windows' text input swallows before any app sees them: the keyboard-layout and IME switch hotkeys
        under HKCU\\Control Panel\\Input Method\\Hot Keys. Windows ships Ctrl+Shift+0 there (switch to the Japanese IME),
        even on PCs without Japanese, which is why Ctrl+Shift+0 often does nothing."""
        found, path = set(), r"Control Panel\Input Method\Hot Keys"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as root:
                n = 0
                while True:
                    try:
                        sub = winreg.EnumKey(root, n)
                    except OSError:
                        break
                    n += 1
                    # only the "switch straight to a keyboard layout" range (0x100-0x11F) is global; the others belong to
                    # Chinese input methods and only apply while one is active (e.g. 0x200+ holds Ctrl+Alt+K)
                    if not (sub.isalnum() and 0x100 <= int(sub, 16) <= 0x11F):
                        continue
                    try:
                        with winreg.OpenKey(root, sub) as k:
                            vk = bytes(winreg.QueryValueEx(k, "Virtual Key")[0])[0]
                            mods = bytes(winreg.QueryValueEx(k, "Key Modifiers")[0])[0]
                    except (OSError, IndexError, TypeError):
                        continue
                    if 0 < vk < 0xFF:  # 0xFF means "not assigned"
                        found.add((frozenset(name for name, _, flag in MODS if mods & flag), vk))
        except OSError:
            pass
        return found

    def hotkeys_taken(combos):
        """Combos another app owns (found by trying to register each one for a moment), or that Windows' keyboard-
        language switching swallows."""
        taken, swallowed = [], input_language_hotkeys()
        for m in combos:
            if not user32.RegisterHotKey(None, 0xBFFF, hotkey_flags(m), m["vk"]):
                taken.append(combo_label(m))
                continue
            user32.UnregisterHotKey(None, 0xBFFF)
            if combo_id(m) in swallowed:
                taken.append(combo_label(m) + SWALLOWED_HINT)
        return taken

    SWALLOWED_HINT = (" (Windows keeps it for switching keyboard language; to free it see "
                      "https://github.com/Shashwat-Gupta57/Kemper/blob/main/docs/DOCUMENTATION.md#ctrlshift0-or-another-combo-never-fires)")

# ---------- macOS and Linux: the same functions, through Quartz (macOS) and X11 (Linux) ----------
else:
    CAN_DESKTOP = IS_LINUX  # a Mac desktop icon would need a real, signed app bundle
    CAN_KEYPACK_FILES = IS_LINUX  # macOS only links file types to app bundles; use Import a keypack… there
    CAN_APP_MENU = IS_LINUX  # likewise Spotlight and Launchpad only list app bundles
    XDG_DATA = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")

    # Kemper stores every key as a Windows virtual-key code, on every system, so settings and keypacks move
    # between systems unchanged. These tables translate those codes for macOS and X11.
    VK_NAMES = {0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc", 0x20: "Space", 0x21: "Page Up",
                0x22: "Page Down", 0x23: "End", 0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
                0x2D: "Insert", 0x2E: "Delete", 0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/",
                0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"}
    VK_NAMES.update({0x30 + i: str(i) for i in range(10)})
    VK_NAMES.update({0x41 + i: chr(0x41 + i) for i in range(26)})
    VK_NAMES.update({0x60 + i: f"Num {i}" for i in range(10)})
    VK_NAMES.update({0x6F + i: f"F{i}" for i in range(1, 25)})
    CHAR_VKS = {name: vk for vk, name in VK_NAMES.items() if len(name) == 1}
    US_SHIFTED = dict(zip('!@#$%^&*()_+{}|:"<>?~', "1234567890-=[]\\;',./`"))  # character -> the key it's on (US)

    X11_KEYSYMS = {0x08: "BackSpace", 0x09: "Tab", 0x0D: "Return", 0x1B: "Escape", 0x20: "space", 0x21: "Prior",
                   0x22: "Next", 0x23: "End", 0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
                   0x2D: "Insert", 0x2E: "Delete", 0xBA: "semicolon", 0xBB: "equal", 0xBC: "comma", 0xBD: "minus",
                   0xBE: "period", 0xBF: "slash", 0xC0: "grave", 0xDB: "bracketleft", 0xDC: "backslash",
                   0xDD: "bracketright", 0xDE: "apostrophe"}
    X11_KEYSYMS.update({0x30 + i: str(i) for i in range(10)})
    X11_KEYSYMS.update({0x41 + i: chr(0x61 + i) for i in range(26)})
    X11_KEYSYMS.update({0x60 + i: f"KP_{i}" for i in range(10)})
    X11_KEYSYMS.update({0x6F + i: f"F{i}" for i in range(1, 25)})
    X11_MODS = {"Ctrl": 0x04, "Alt": 0x08, "Shift": 0x01, "Win": 0x40}  # ControlMask, Mod1, ShiftMask, Mod4

    # macOS virtual key codes (Carbon kVK_*), which name physical keys
    MAC_KEYCODES = {0x41: 0x00, 0x53: 0x01, 0x44: 0x02, 0x46: 0x03, 0x48: 0x04, 0x47: 0x05, 0x5A: 0x06, 0x58: 0x07,
                    0x43: 0x08, 0x56: 0x09, 0x42: 0x0B, 0x51: 0x0C, 0x57: 0x0D, 0x45: 0x0E, 0x52: 0x0F, 0x59: 0x10,
                    0x54: 0x11, 0x31: 0x12, 0x32: 0x13, 0x33: 0x14, 0x34: 0x15, 0x36: 0x16, 0x35: 0x17, 0xBB: 0x18,
                    0x39: 0x19, 0x37: 0x1A, 0xBD: 0x1B, 0x38: 0x1C, 0x30: 0x1D, 0xDD: 0x1E, 0x4F: 0x1F, 0x55: 0x20,
                    0xDB: 0x21, 0x49: 0x22, 0x50: 0x23, 0x0D: 0x24, 0x4C: 0x25, 0x4A: 0x26, 0xDE: 0x27, 0x4B: 0x28,
                    0xBA: 0x29, 0xDC: 0x2A, 0xBC: 0x2B, 0xBF: 0x2C, 0x4E: 0x2D, 0x4D: 0x2E, 0xBE: 0x2F, 0x09: 0x30,
                    0x20: 0x31, 0xC0: 0x32, 0x08: 0x33, 0x1B: 0x35,
                    0x70: 0x7A, 0x71: 0x78, 0x72: 0x63, 0x73: 0x76, 0x74: 0x60, 0x75: 0x61, 0x76: 0x62, 0x77: 0x64,
                    0x78: 0x65, 0x79: 0x6D, 0x7A: 0x67, 0x7B: 0x6F, 0x7C: 0x69, 0x7D: 0x6B, 0x7E: 0x71, 0x7F: 0x6A,
                    0x80: 0x40, 0x81: 0x4F, 0x82: 0x50, 0x83: 0x5A,
                    0x2D: 0x72, 0x24: 0x73, 0x21: 0x74, 0x2E: 0x75, 0x23: 0x77, 0x22: 0x79,
                    0x25: 0x7B, 0x27: 0x7C, 0x28: 0x7D, 0x26: 0x7E,
                    0x60: 0x52, 0x61: 0x53, 0x62: 0x54, 0x63: 0x55, 0x64: 0x56, 0x65: 0x57, 0x66: 0x58, 0x67: 0x59,
                    0x68: 0x5B, 0x69: 0x5C}
    MAC_FLAGS = {"Ctrl": 0x40000, "Alt": 0x80000, "Shift": 0x20000, "Win": 0x100000}  # kCGEventFlagMask*

    def key_name(vk):
        return VK_NAMES.get(vk, f"Key {vk}")

    def vk_for_char(ch):
        """The key that types ch on a US layout: (vk, needs Shift), or None."""
        if ch in US_SHIFTED:
            return CHAR_VKS[US_SHIFTED[ch]], True
        vk = CHAR_VKS.get(ch.upper())
        return (vk, False) if vk else None

    def pythonw():
        return sys.executable

    # ---- typing ----
    def _x_display():
        from Xlib import display
        return display.Display()

    def _mods_down():
        if IS_MAC:
            import Quartz
            flags = Quartz.CGEventSourceFlagsState(Quartz.kCGEventSourceStateHIDSystemState)
            return bool(flags & sum(MAC_FLAGS.values()))
        from Xlib import XK
        d = _x_display()
        try:
            keys = d.query_keymap()
            for name in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Super_L", "Super_R", "Meta_L", "Meta_R"):
                code = d.keysym_to_keycode(XK.string_to_keysym(name))
                if code and keys[code // 8] & (1 << (code % 8)):
                    return True
            return False
        finally:
            d.close()

    def _x_type(text):
        """Type Unicode text with the X11 test extension, like xdotool: characters the keyboard layout lacks get
        a spare key code mapped to them for a moment."""
        from Xlib import X, XK
        from Xlib.ext import xtest
        d = _x_display()
        try:
            lo, hi = d.display.info.min_keycode, d.display.info.max_keycode
            table = d.get_keyboard_mapping(lo, hi - lo + 1)
            spare = next((lo + i for i in reversed(range(len(table))) if not any(table[i])), None)
            shift = d.keysym_to_keycode(XK.string_to_keysym("Shift_L"))
            for ch in text:
                if ch in "\n\t":
                    sym = XK.string_to_keysym("Return" if ch == "\n" else "Tab")
                else:  # Latin-1 keysyms equal their code points; the rest use X11's Unicode keysyms
                    sym = ord(ch) if 0x20 <= ord(ch) <= 0x7E or 0xA0 <= ord(ch) <= 0xFF else 0x01000000 | ord(ch)
                code, shifted = d.keysym_to_keycode(sym), False
                if code and d.keycode_to_keysym(code, 0) != sym:
                    shifted = d.keycode_to_keysym(code, 1) == sym
                    code = code if shifted else 0  # on a level we can't reach with Shift (AltGr): use the spare key
                if not code:
                    if spare is None:
                        continue
                    d.change_keyboard_mapping(spare, [(sym,) * 4])
                    d.sync()
                    time.sleep(0.02)  # let apps see the new mapping before the key arrives
                    code = spare
                if shifted:
                    xtest.fake_input(d, X.KeyPress, shift)
                xtest.fake_input(d, X.KeyPress, code)
                xtest.fake_input(d, X.KeyRelease, code)
                if shifted:
                    xtest.fake_input(d, X.KeyRelease, shift)
                d.sync()
            if spare is not None:
                time.sleep(0.05)
                d.change_keyboard_mapping(spare, [(X.NoSymbol,) * 4])
                d.sync()
        finally:
            d.close()

    def type_text(text):
        end = time.time() + 2
        while time.time() < end and safely(_mods_down):
            time.sleep(0.01)  # held modifiers would turn our typed characters into shortcuts
        text = text.replace("\r\n", "\n")
        if IS_MAC:
            from pynput.keyboard import Controller
            Controller().type(text)  # Unicode; \n presses Enter
        else:
            _x_type(text)

    # ---- hotkeys ----
    class _Hotkeys:
        def __init__(self, rows, on_fire=None, picker=None, on_picker=None):
            self.rows, self.on_fire, self.picker, self.on_picker = rows, on_fire, picker, on_picker
            self.failed, self.ready = [], threading.Event()

        def _wanted(self):
            return [(m, ("type", m)) for m in self.rows] + ([(self.picker, ("picker", None))] if self.picker else [])

        def _fire(self, kind, m):
            if kind == "picker":
                if self.on_picker:
                    self.on_picker()
                return
            type_text(m["text"])
            if self.on_fire:
                self.on_fire(m)

    class _MacHotkeys(_Hotkeys):
        """A Quartz event tap (through pynput) that sees every key press and swallows Kemper's combos."""
        def start(self):
            self._tap = None
            try:
                import Quartz
                from pynput import keyboard
            except ImportError:
                self.failed.append("every shortcut (install pynput:  python3 -m pip install pynput)")
                return self.ready.set()
            table, swallowed, mask = {}, set(), sum(MAC_FLAGS.values())
            for m, action in self._wanted():
                code = MAC_KEYCODES.get(m["vk"])
                if code is None:
                    self.failed.append(combo_label(m))
                else:
                    table[(code, sum(MAC_FLAGS[n] for n in m["mods"]))] = action

            def intercept(kind, event):
                if kind not in (Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp):
                    return event
                code = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
                if kind == Quartz.kCGEventKeyUp:
                    if code in swallowed:
                        swallowed.discard(code)
                        return None
                    return event
                hit = table.get((code, Quartz.CGEventGetFlags(event) & mask))
                if not hit:
                    return event
                swallowed.add(code)
                if not Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat):
                    threading.Thread(target=self._fire, args=hit, daemon=True).start()
                return None  # the app in front never sees the combo

            self._tap = keyboard.Listener(darwin_intercept=intercept)
            self._tap.start()
            self._tap.wait()
            if not getattr(self._tap, "IS_TRUSTED", True):
                self.failed.append("every shortcut: allow Kemper in System Settings → Privacy & Security → Accessibility")
            self.ready.set()

        def stop(self):
            if self._tap:
                self._tap.stop()

    class _X11Hotkeys(_Hotkeys, threading.Thread):
        """X11 key grabs on the root window: the combos come to Kemper and never reach the app in front."""
        def __init__(self, *args, **kwargs):
            _Hotkeys.__init__(self, *args, **kwargs)
            threading.Thread.__init__(self, daemon=True)
            self._halt = threading.Event()

        def run(self):
            try:
                from Xlib import X, XK, error
                d = _x_display()
            except Exception as e:
                self.failed.append("every shortcut: " + ("install python-xlib (python3 -m pip install python-xlib)" if isinstance(e, ImportError)
                                                         else "no X11 display. Kemper needs an Xorg session"))
                return self.ready.set()
            root = d.screen().root
            locks = (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask)  # so Caps Lock and Num Lock don't matter
            table = {}
            for m, action in self._wanted():
                sym = XK.string_to_keysym(X11_KEYSYMS.get(m["vk"], ""))
                code = d.keysym_to_keycode(sym) if sym else 0
                mask = sum(X11_MODS[n] for n in m["mods"])
                if not code:
                    self.failed.append(combo_label(m))
                    continue
                catch = error.CatchError(error.BadAccess)
                for extra in locks:
                    root.grab_key(code, mask | extra, True, X.GrabModeAsync, X.GrabModeAsync, onerror=catch)
                d.sync()
                if catch.get_error():  # another app already grabbed it
                    for extra in locks:
                        root.ungrab_key(code, mask | extra)
                    self.failed.append(combo_label(m))
                    continue
                table[(code, mask)] = action
            d.sync()
            self.ready.set()
            down, held = set(), None
            while not self._halt.is_set():
                while held or d.pending_events():
                    ev, held = held or d.next_event(), None
                    if ev.type == X.KeyRelease:
                        if d.pending_events():  # X sends auto-repeat as release+press with the same timestamp
                            nxt = d.next_event()
                            if nxt.type == X.KeyPress and nxt.detail == ev.detail and nxt.time == ev.time:
                                continue
                            held = nxt
                        down.discard(ev.detail)
                    elif ev.type == X.KeyPress:
                        hit = table.get((ev.detail, ev.state & 0x4D))  # Shift|Control|Mod1|Mod4
                        if hit and ev.detail not in down:
                            down.add(ev.detail)
                            threading.Thread(target=self._fire, args=hit, daemon=True).start()
                self._halt.wait(0.02)
            for code, mask in table:
                for extra in locks:
                    root.ungrab_key(code, mask | extra)
            d.sync()
            d.close()

        def stop(self):
            self._halt.set()
            self.join(2)

    Listener = _MacHotkeys if IS_MAC else _X11Hotkeys

    # ---- start at login: a LaunchAgent on macOS, an XDG autostart entry on Linux ----
    LAUNCH_AGENT = os.path.expanduser("~/Library/LaunchAgents/in.talken.kemper.plist")
    AUTOSTART = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "autostart", "kemper.desktop")

    def desktop_exec(args):
        """Arguments for a .desktop file's Exec= line, quoted the way the freedesktop spec wants."""
        return " ".join(a if re.fullmatch(r"[\w./:%=-]+", a) else '"' + re.sub(r'(["`$\\])', r"\\\1", a) + '"' for a in args)

    def startup_args():
        return [pythonw(), os.path.abspath(__file__), "--hidden"]

    def startup_cmd():
        return " ".join(json.dumps(a) for a in startup_args()) if IS_MAC else desktop_exec(startup_args())

    def startup_value():
        try:
            if IS_MAC:
                with open(LAUNCH_AGENT, "rb") as f:
                    return " ".join(json.dumps(a) for a in plistlib.load(f).get("ProgramArguments", []))
            with open(AUTOSTART, encoding="utf-8") as f:
                return next((line[5:].strip() for line in f if line.startswith("Exec=")), None)
        except (OSError, ValueError):
            return None

    def desktop_entry(exec_args, extra=""):
        return ("[Desktop Entry]\nType=Application\nName=Kemper\nGenericName=Key Mapper\n"
                "Comment=Type any character with a key combo\nExec=" + desktop_exec(exec_args) +
                "\nIcon=" + icon_path() + "\nTerminal=false\nCategories=Utility;\n" + extra)

    def _write(path, content, mode=0o644):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.chmod(path + ".tmp", mode)
        os.replace(path + ".tmp", path)

    def _remove(path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    def set_startup(on):
        path = LAUNCH_AGENT if IS_MAC else AUTOSTART
        if not on:
            return _remove(path)
        if IS_MAC:
            _write(path, plistlib.dumps({"Label": "in.talken.kemper", "ProgramArguments": startup_args(),
                                         "RunAtLoad": True, "ProcessType": "Interactive"}))
        else:
            _write(path, desktop_entry(startup_args(), "X-GNOME-Autostart-enabled=true\n"))

    # ---- desktop shortcut and .kmppck files (Linux) ----
    def _user_dir(name, fallback):
        try:
            p = subprocess.run(["xdg-user-dir", name], capture_output=True, text=True, timeout=3).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            p = ""
        return p if p and os.path.isdir(p) else os.path.expanduser(fallback)

    APP_ENTRY = os.path.join(XDG_DATA, "applications", "kemper.desktop")

    def desktop_path():
        return os.path.join(_user_dir("DESKTOP", "~/Desktop"), "kemper.desktop")

    def desktop_enabled():
        return CAN_DESKTOP and os.path.exists(desktop_path())

    def _app_entry():
        return desktop_entry([pythonw(), os.path.abspath(__file__)])

    def set_desktop(on):
        """A launcher with Kemper's icon on the desktop."""
        if not CAN_DESKTOP:
            raise OSError("desktop shortcuts aren't available on macOS")
        if not on:
            return _remove(desktop_path())
        _write(desktop_path(), _app_entry(), 0o755)
        if shutil.which("gio"):  # GNOME only runs desktop launchers it's been told to trust
            subprocess.run(["gio", "set", desktop_path(), "metadata::trusted", "true"], capture_output=True)

    # App menu: what makes searching for "Kemper" find it. macOS only lists real app bundles, so Linux only.
    def app_menu_registered():
        try:
            with open(APP_ENTRY, encoding="utf-8") as f:
                return f.read() == _app_entry()
        except OSError:
            return False

    def register_app_menu():
        if CAN_APP_MENU and not app_menu_registered():
            _write(APP_ENTRY, _app_entry(), 0o755)

    def unregister_app_menu():
        _remove(APP_ENTRY)

    KEYPACK_MIME = "application/x-kemper-keypack"

    def _keypack_files():
        icon = base64.b64decode(ICON_PNGS[256])
        return {
            os.path.join(XDG_DATA, "mime", "packages", "kemper-keypack.xml"):
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">\n'
                f'  <mime-type type="{KEYPACK_MIME}">\n    <comment>Kemper keypack</comment>\n'
                '    <icon name="application-x-kemper-keypack"/>\n    <glob pattern="*.kmppck"/>\n  </mime-type>\n</mime-info>\n',
            os.path.join(XDG_DATA, "applications", "kemper-keypack.desktop"):
                desktop_entry([pythonw(), os.path.abspath(__file__), "--keypack", "%f"], f"MimeType={KEYPACK_MIME};\nNoDisplay=true\n"),
            os.path.join(XDG_DATA, "icons", "hicolor", "256x256", "apps", "kemper.png"): icon,
            os.path.join(XDG_DATA, "icons", "hicolor", "256x256", "mimetypes", "application-x-kemper-keypack.png"): icon,
        }

    def _refresh_desktop_databases():
        for cmd in (["update-mime-database", os.path.join(XDG_DATA, "mime")],
                    ["update-desktop-database", os.path.join(XDG_DATA, "applications")],
                    ["xdg-mime", "default", "kemper-keypack.desktop", KEYPACK_MIME]):
            if shutil.which(cmd[0]):
                subprocess.run(cmd, capture_output=True)

    def keypacks_registered():
        path, want = next((p, c) for p, c in _keypack_files().items() if p.endswith(".desktop"))
        try:
            with open(path, encoding="utf-8") as f:
                return f.read() == want
        except OSError:
            return False

    def register_keypacks():
        """Make .kmppck files open in Kemper, with Kemper's icon. Current user only; redone if Kemper moved."""
        if not CAN_KEYPACK_FILES:
            return
        changed = False
        for path, content in _keypack_files().items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            try:
                with open(path, "rb") as f:
                    if f.read() == data:
                        continue
            except OSError:
                pass
            _write(path, data)
            changed = True
        if changed:
            _refresh_desktop_databases()

    def unregister_keypacks():
        if CAN_KEYPACK_FILES:
            for path in _keypack_files():
                _remove(path)
            _refresh_desktop_databases()

    # ---- clipboard, folders, theme ----
    def set_clipboard(text):
        if IS_MAC:
            tools = [["pbcopy"]]
        else:
            tools = ([["wl-copy"]] if os.environ.get("WAYLAND_DISPLAY") else []) + [
                ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
        for cmd in tools:
            if shutil.which(cmd[0]):
                try:
                    subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=5, capture_output=True,
                                   env={**os.environ, "LANG": os.environ.get("LANG") or "en_US.UTF-8"})
                    return True
                except (OSError, subprocess.SubprocessError):
                    pass
        return False

    def documents_folder():
        return _user_dir("DOCUMENTS", "~/Documents") if IS_LINUX else os.path.expanduser("~/Documents")

    def os_is_dark():
        try:
            if IS_MAC:
                out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True, timeout=3).stdout
                return "dark" in out.lower()
            out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                                 capture_output=True, text=True, timeout=3).stdout
            if "dark" in out:
                return True
            out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                                 capture_output=True, text=True, timeout=3).stdout
            return "dark" in out.lower()
        except (OSError, subprocess.SubprocessError):
            return False

    # ---- windows on screen ----
    def own_window(title=APP):
        return None

    def dark_title_bar(dark, title=APP):
        pass  # macOS and GNOME draw the title bar to match the system theme themselves

    def _net_active_window(d):
        from Xlib import X
        prop = d.screen().root.get_full_property(d.intern_atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType)
        return prop.value[0] if prop and len(prop.value) else None

    def active_app():
        if IS_MAC:
            from AppKit import NSWorkspace
            return NSWorkspace.sharedWorkspace().frontmostApplication()
        d = _x_display()
        try:
            return _net_active_window(d)
        finally:
            d.close()

    def activate(app):
        if not app:
            return
        if IS_MAC:
            return app.activateWithOptions_(2)  # NSApplicationActivateIgnoringOtherApps
        from Xlib import X, protocol
        d = _x_display()
        try:  # ask the window manager to focus it (EWMH _NET_ACTIVE_WINDOW, source = pager)
            root = d.screen().root
            ev = protocol.event.ClientMessage(window=d.create_resource_object("window", app), client_type=d.intern_atom("_NET_ACTIVE_WINDOW"),
                                              data=(32, [2, X.CurrentTime, 0, 0, 0]))
            root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            d.sync()
        finally:
            d.close()

    def _cursor():
        if IS_MAC:
            import Quartz
            p = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
            return int(p.x), int(p.y)
        d = _x_display()
        try:
            p = d.screen().root.query_pointer()
            return p.root_x, p.root_y
        finally:
            d.close()

    def _screen_size():
        if IS_MAC:
            import Quartz
            size = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID()).size
            return int(size.width), int(size.height)
        d = _x_display()
        try:
            return d.screen().width_in_pixels, d.screen().height_in_pixels
        finally:
            d.close()

    def _front_app():
        from AppKit import NSApplication
        from PyObjCTools import AppHelper
        AppHelper.callAfter(NSApplication.sharedApplication().activateIgnoringOtherApps_, True)

    def show_popup(window, title):
        pos, screen = safely(_cursor), safely(_screen_size) or (10**6, 10**6)
        if pos:  # by the mouse, kept on screen (the picker is 380 x 460)
            x = min(max(pos[0] - 190, 0), max(screen[0] - 380, 0))
            y = min(max(pos[1] - 40, 0), max(screen[1] - 460, 0))
            safely(window.move, x, y)
        window.show()
        if IS_MAC:
            safely(_front_app)

    def bring_to_front(title=APP):
        if IS_MAC:
            _front_app()

    def allow_foreground():
        pass

    def app_identity():
        pass

    def alert(msg):
        print(msg, file=sys.stderr)
        if IS_MAC:
            subprocess.run(["osascript", "-e", 'display alert "Kemper" message ' + json.dumps(msg)], capture_output=True)
        elif shutil.which("zenity"):
            subprocess.run(["zenity", "--error", "--title=Kemper", "--text=" + msg], capture_output=True)

    def show_file(path):
        subprocess.Popen(["open", "-R", path] if IS_MAC else ["xdg-open", os.path.dirname(path)])

    def mac_trusted():
        """Whether macOS lets this app see and send key presses (Accessibility)."""
        try:
            lib = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
            lib.AXIsProcessTrusted.restype = ctypes.c_bool
            return lib.AXIsProcessTrusted()
        except OSError:
            return False

    def platform_checks(check):
        lib = "pynput" if IS_MAC else "python-xlib"
        try:
            __import__("pynput" if IS_MAC else "Xlib")
        except ImportError:
            return check(2, f"{lib} isn't installed, so shortcuts can't work. Fix:  python3 -m pip install {lib}")
        if IS_MAC:
            ok = mac_trusted()
            return check(0 if ok else 2, "Kemper may watch and type keys (Accessibility is on)" if ok else
                         "Kemper needs Accessibility access to see and type keys. Fix: System Settings → Privacy & Security → "
                         "Accessibility, then turn on the app you start Kemper from (Terminal, or Python)")
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            check(2, "This is a Wayland session, where apps can't have global hotkeys. Fix: log out, pick “Ubuntu on Xorg” "
                     "with the gear at the login screen, and log in again")
        elif not os.environ.get("DISPLAY"):
            check(2, "No X11 display, so shortcuts can't work. Run Kemper inside your desktop session")
        else:
            check(0, "X11 session: global hotkeys work")
        tool = next((t for t in ("wl-copy", "xclip", "xsel") if shutil.which(t)), None)
        check(0 if tool else 1, f"Clipboard tool: {tool}" if tool else
              "No clipboard tool, so Copy instructions can't copy. Fix:  sudo apt install xclip")

    def hotkeys_taken(combos):
        return None  # no cheap test here; Kemper reports taken combos when it starts

    def input_language_hotkeys():
        return set()  # a Windows-only trap

    SWALLOWED_HINT = ""

# ---------- mappings ----------
def combo_id(m):
    return (frozenset(m["mods"]), m["vk"])

def combo_label(m):
    order = [n for n, _, _ in MODS]
    return " + ".join(sorted(m["mods"], key=order.index) + [m["key"]])

MOD_DISPLAY = {"Win": "Cmd", "Alt": "Option"} if IS_MAC else {"Win": "Super"} if IS_LINUX else {}

def display_label(m):
    """combo_label in this system's words (Cmd and Option on a Mac, Super on Linux), for the window.
    Settings, keypacks and the CLI keep Kemper's own names, so they work on every system."""
    order = [n for n, _, _ in MODS]
    return " + ".join([MOD_DISPLAY.get(n, n) for n in sorted(m["mods"], key=order.index)] + [m["key"]])

def find_conflicts(rows):
    ids = [combo_id(r) for r in rows if r["vk"]]
    return {i for i in ids if ids.count(i) > 1}

def clean_picker(p):
    """Validate the quick picker's settings; raises ValueError."""
    names = {n for n, _, _ in MODS}
    if not (isinstance(p, dict) and isinstance(p.get("enabled"), bool) and isinstance(p.get("mods"), list)
            and set(p["mods"]) <= names and isinstance(p.get("vk"), int) and 0 < p["vk"] < 255
            and isinstance(p.get("key"), str) and p["key"]):
        raise ValueError("The quick picker needs a key combo.")
    return {"enabled": p["enabled"], "mods": sorted(set(p["mods"]), key=[n for n, _, _ in MODS].index),
            "vk": p["vk"], "key": p["key"]}

def clean_mapping(r):
    """Validate one mapping (from the UI, the CLI or a keypack file); raises ValueError."""
    names = {n for n, _, _ in MODS}
    mods, vk, key, text = (r.get("mods"), r.get("vk"), r.get("key"), r.get("text")) if isinstance(r, dict) else (None,) * 4
    if not (isinstance(mods, list) and all(isinstance(m, str) for m in mods) and set(mods) <= names
            and isinstance(vk, int) and not isinstance(vk, bool) and 0 < vk < 255
            and isinstance(key, str) and 0 < len(key) <= 40 and isinstance(text, str) and text):
        raise ValueError("Every shortcut needs both keys and text.")
    if len(text) > TEXT_MAX:
        raise ValueError(f"A shortcut's text can be at most {TEXT_MAX:,} characters.")
    return {"mods": sorted(set(mods), key=[n for n, _, _ in MODS].index), "vk": vk, "key": key, "text": text}

def clean_mappings(rows, picker=None):
    """Validate mappings coming from the UI or CLI; raises ValueError so a bad config is never saved."""
    if not isinstance(rows, list):
        raise ValueError("Every shortcut needs both keys and text.")
    out = [clean_mapping(r) for r in rows]
    if find_conflicts(out):
        raise ValueError("Two or more shortcuts use the same keys.")
    if picker and picker["enabled"] and combo_id(picker) in {combo_id(m) for m in out}:
        raise ValueError(f"{combo_label(picker)} opens the quick picker, so a shortcut can't use it too.")
    return out

def load():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if isinstance(data, list):  # v1 config was a bare list
        data = {"mappings": data}
    return {"mappings": data.get("mappings", []), "appearance": data.get("appearance", "system"),
            "active": data.get("active", True), "picker": {**DEFAULT_PICKER, **data.get("picker", {})}}

def save(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG)  # atomic, so a crash can't leave a half-written config

# ---------- keypacks: shareable sets of shortcuts in .kmppck files ----------
# A keypack is JSON: {"format": "kemper-keypack", "version": 1, "name": ..., "mappings": [{"keys": "Alt+2", "text": "²"}]}.
# Its name lives inside the file, so the file can be called anything. The "keys" form is easy for people and AI to
# write; Kemper's exact form ({"mods", "vk", "key", "text"}) is accepted too and used for keys "keys" can't name.
def takes_common_keys(m):
    """Ctrl+C, V, S, … (Cmd on a Mac): taking these over breaks copy, paste, save and friends in every app."""
    return m["mods"] == ["Win" if IS_MAC else "Ctrl"] and m["key"] in tuple("ACFNOPSTVWXYZ")

def keypack_mapping(m):
    """One keypack shortcut in either form, validated. Raises ValueError."""
    if isinstance(m, dict) and isinstance(m.get("keys"), str):
        return clean_mapping({**parse_combo(m["keys"]), "text": m.get("text")})
    return clean_mapping(m)

def keypack_entry(m):
    """How a shortcut is written into a keypack: the readable "keys" form whenever it reads back as the same keys."""
    keys = combo_label(m).replace(" + ", "+")
    try:
        if combo_id(parse_combo(keys)) == combo_id(m):
            return {"keys": keys, "text": m["text"]}
    except ValueError:
        pass
    return m

def parse_keypack(raw, fallback_name="Keypack"):
    """Keypack text to {"name", "mappings"}. Lenient about text around the JSON (AI replies often add some),
    strict about what's inside: it may be a stranger's. Raises ValueError."""
    if len(raw) > KEYPACK_MAX_BYTES:
        raise ValueError("This is too big to be a keypack.")
    start, end = raw.find("{"), raw.rfind("}")
    try:
        data = json.loads(raw[start:end + 1]) if 0 <= start < end else None
    except ValueError:
        data = None
    if not (isinstance(data, dict) and data.get("format") == "kemper-keypack" and isinstance(data.get("mappings"), list)):
        raise ValueError("This isn't a Kemper keypack.")
    version = data.get("version", 1)
    if not isinstance(version, int) or version > 1:
        raise ValueError("This keypack was made by a newer Kemper. Update Kemper to open it.")
    if len(data["mappings"]) > KEYPACK_MAX_ITEMS:
        raise ValueError(f"This keypack has more than {KEYPACK_MAX_ITEMS} shortcuts.")
    mappings = []
    for n, m in enumerate(data["mappings"], 1):
        try:
            mappings.append(keypack_mapping(m))
        except ValueError as e:
            keys = m.get("keys") if isinstance(m, dict) and isinstance(m.get("keys"), str) else ""
            raise ValueError(f"Shortcut {n}{f' ({keys[:40]})' if keys else ''} in this keypack is broken: {e}") from None
    name = data.get("name")
    name = name.strip()[:100] if isinstance(name, str) and name.strip() else fallback_name
    return {"name": name, "mappings": mappings}

def read_keypack(path):
    """Load a keypack file, possibly a stranger's: size-capped and every field validated. Raises ValueError."""
    try:
        if os.path.getsize(path) > KEYPACK_MAX_BYTES:
            raise ValueError("This file is too big to be a keypack.")
        with open(path, encoding="utf-8-sig") as f:  # -sig: Notepad may add a BOM
            raw = f.read()
    except OSError:
        raise ValueError("Kemper couldn't open this file.") from None
    except UnicodeDecodeError:
        raise ValueError("This isn't a Kemper keypack.") from None
    return parse_keypack(raw, os.path.splitext(os.path.basename(path))[0])

def write_keypack(path, name, mappings):
    """Save a keypack. Conflicting or half-filled shortcuts are refused, like in Kemper itself. Returns the name."""
    name = name.strip()[:100] if isinstance(name, str) else ""
    if not name:
        raise ValueError("Give the keypack a name.")
    mappings = clean_mappings(mappings)
    if not mappings:
        raise ValueError("Add at least one shortcut first.")
    data = {"format": "kemper-keypack", "version": 1, "name": name, "made_with": f"Kemper {VERSION}",
            "mappings": [keypack_entry(m) for m in mappings]}
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)
    return name

def keypack_filename(text):
    """A safe Windows file name for a keypack, ending in .kmppck. Raises ValueError."""
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(text)).strip().rstrip(". ")
    if stem.lower().endswith(KEYPACK_EXT):
        stem = stem[:-len(KEYPACK_EXT)].rstrip(". ")
    if not stem:
        raise ValueError("Give the file a name.")
    if re.fullmatch(r"(con|prn|aux|nul|com\d|lpt\d)", stem, re.I):
        raise ValueError(f"Windows doesn't allow a file called {stem}. Pick another name.")
    return stem[:120] + KEYPACK_EXT

def keypack_preview(pack, cfg):
    """Each keypack shortcut, plus what importing it would do to this Kemper (level: bad, warn, same or '')."""
    mine = {combo_id(m): m for m in cfg["mappings"]}
    ids = [combo_id(m) for m in pack]
    picker = cfg["picker"]
    items = []
    for m in pack:
        cid, label, old = combo_id(m), display_label(m), mine.get(combo_id(m))
        if old and old["text"] == m["text"]:
            issue, level = "Already in your Kemper", "same"
        elif ids.count(cid) > 1:
            issue, level = "Used twice in this keypack", "bad"
        elif old:
            issue, level = f"Same keys as your {one_line(old['text'])[:24]}", "bad"
        elif picker["enabled"] and cid == combo_id(picker):
            issue, level = "Same keys as your quick picker", "bad"
        elif set(m["mods"]) <= {"Shift"}:
            issue, level = "Replaces normal typing of this key", "warn"
        elif takes_common_keys(m):
            issue, level = f"Replaces {label} in every app", "warn"
        else:
            issue, level = "", ""
        items.append({**m, "label": label, "issue": issue, "level": level})
    return items

def hotkey_flags(m):
    return MOD_NOREPEAT | sum(f for n, _, f in MODS if n in m["mods"])

# ---------- shared by every system ----------
def safely(fn, *args):
    """Best-effort OS niceties (focus, window placement): they must never break Kemper."""
    try:
        return fn(*args)
    except Exception:
        return None

def startup_enabled():
    return startup_value() == startup_cmd()

def icon_path():
    """Kemper's icon as a real file, written from the PNGs embedded at the end: .ico on Windows, .png elsewhere."""
    pngs = [(size, base64.b64decode(data)) for size, data in sorted(ICON_PNGS.items())]
    if IS_WIN:
        path = os.path.join(os.path.dirname(CONFIG), "kemper.ico")
        offset = 6 + 16 * len(pngs)
        entries, blobs = b"", b""
        for size, png in pngs:  # an .ico may hold PNG images directly (Windows Vista and later)
            entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset + len(blobs))
            blobs += png
        data = struct.pack("<HHH", 0, 1, len(pngs)) + entries + blobs
    else:
        path, data = os.path.join(os.path.dirname(CONFIG), "kemper.png"), dict(pngs)[256]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)
    except OSError:
        pass  # an older copy may be in use; it's the same icon
    return path

# ---------- engine, shared by the window and --cli ----------
class Api:
    """Methods here are callable from JS as window.pywebview.api.<name>. Underscored attrs stay private."""
    def __init__(self, on_fire=None, on_reload=None):
        self._cfg = load()
        self._listener = None
        self._lock = threading.Lock()
        self._window = None
        self._picker = None  # the quick picker popup; only exists when the window version runs
        self._picker_open = False
        self._picker_target = None  # the app that had focus when the picker opened
        self._editor = None  # the Keypack Editor window, while it's open
        self._editor_path = None
        self._editor_ai = False  # open the editor straight into the AI sheet
        self._editor_dirty = False
        self._pending_keypack = None  # a .kmppck waiting for the import question
        self._quitting = False
        self._notice = ""
        self._on_fire, self._on_reload = on_fire, on_reload
        self._done = threading.Event()
        self._start()

    def _start(self):
        with self._lock:
            if self._listener or not self._cfg["active"]:
                return
            picker = self._cfg["picker"] if self._picker and self._cfg["picker"]["enabled"] else None
            self._listener = Listener([dict(m) for m in self._cfg["mappings"]], self._on_fire, picker, self._open_picker)
            self._listener.start()
            self._listener.ready.wait(2)
            failed = self._listener.failed
            self._notice = ("Already used by another app, so these won't work: " + ", ".join(failed)) if failed else ""

    def _stop(self):
        with self._lock:
            if self._listener:
                self._listener.stop()
                self._listener = None

    def _reload(self):
        # shortcut: a CLI edit replaces unsaved edits in the open window; merge them if that ever bites.
        self._cfg = load()
        self._stop()
        self._start()
        if self._window:
            self._window.evaluate_js("refresh()")
        if self._on_reload:
            self._on_reload()

    def state(self):
        return {**self._cfg, "startup": startup_enabled(), "desktop": desktop_enabled(), "notice": self._notice,
                "os": OS_NAME, "can_desktop": CAN_DESKTOP, "can_keypack_files": CAN_KEYPACK_FILES, "mod_names": MOD_DISPLAY}

    def key_name(self, vk):
        return key_name(int(vk))

    def capture(self, on):
        # Hotkeys are paused while recording so pressing an existing combo doesn't type its text.
        self._stop() if on else self._start()

    def save(self, rows, picker=None):
        try:
            picker = clean_picker(picker) if picker is not None else self._cfg["picker"]
            mappings = clean_mappings(rows, picker)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        self._cfg["mappings"], self._cfg["picker"] = mappings, picker
        save(self._cfg)
        self._stop()
        self._start()
        return {"ok": True, "mappings": mappings, "picker": picker, "notice": self._notice}

    def set_startup(self, on):
        try:
            set_startup(bool(on))
        except OSError:
            pass
        return startup_enabled()

    def set_desktop(self, on):
        try:
            set_desktop(bool(on))
        except OSError:
            pass
        return desktop_enabled()

    def set_appearance(self, mode, dark):
        if mode in ("system", "light", "dark"):
            self._cfg["appearance"] = mode
            save(self._cfg)
        dark_title_bar(bool(dark))
        if self._editor:
            self._editor.evaluate_js(f"setDark({json.dumps(bool(dark))})")
            dark_title_bar(bool(dark), EDITOR_TITLE)

    def set_active(self, on):
        """Deactivate turns every shortcut off without closing Kemper; the choice survives restarts."""
        self._cfg["active"] = bool(on)
        save(self._cfg)
        self._stop()
        self._start()
        return self.state()

    def quit(self):
        self._quitting = True
        self._stop()
        self._done.set()
        if self._window:
            threading.Timer(2, os._exit, (0,)).start()  # backstop: Quit must always end the process
            for w in (self._picker, self._editor):
                if w:
                    w.destroy()
            self._window.destroy()

    def _on_closing(self):
        if self._quitting:
            return True
        self._window.hide()  # closing only hides; hotkeys keep working
        return False

    # --- keypacks: importing into Kemper ---
    def read_keypack(self, path):
        try:
            pack = read_keypack(path)
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": str(e), "file": os.path.basename(str(path))}
        return {"ok": True, "name": pack["name"], "file": os.path.basename(path), "folder": os.path.dirname(os.path.abspath(path)),
                "items": keypack_preview(pack["mappings"], self._cfg)}

    def take_pending_keypack(self):
        path, self._pending_keypack = self._pending_keypack, None
        return path

    def _open_keypack(self, path):
        if not self._window:
            return  # --cli has no window to ask in
        self._pending_keypack = path
        self._window.show()
        self._window.restore()
        safely(bring_to_front)
        try:
            self._window.evaluate_js("openPendingKeypack()")
        except Exception:
            pass  # page still loading; it asks for the pending keypack once it's ready

    def choose_keypack(self):
        import webview
        r = self._window.create_file_dialog(webview.FileDialog.OPEN, directory=documents_folder(),
                                            file_types=("Kemper keypacks (*.kmppck)", "All files (*.*)"))
        return (r[0] if isinstance(r, (list, tuple)) else r) or None

    # --- keypacks: the editor window ---
    def open_marketplace(self):
        """Ready-made keypacks on the website, in the default browser."""
        webbrowser.open(MARKETPLACE_URL)

    def open_editor(self, path=None, ai=False):
        import webview
        if self._editor:
            self._editor.show()
            self._editor.restore()
            self._editor.evaluate_js("aiSheet()" if ai else f"requestLoad({json.dumps(path)})")
            return
        self._editor_path, self._editor_ai, self._editor_dirty = path, bool(ai), False
        dark = self._dark()
        self._editor = webview.create_window(EDITOR_TITLE, html=EDITOR_HTML, js_api=self, width=780, height=660,
                                             min_size=(620, 460), background_color="#000000" if dark else "#F2F2F7",
                                             text_select=True)
        self._editor.events.closing += self._on_editor_closing
        self._editor.events.closed += self._on_editor_closed
        self._editor.events.shown += lambda: dark_title_bar(self._dark(), EDITOR_TITLE)

    def editor_boot(self):
        return {"dark": self._dark(), "path": self._editor_path, "ai": self._editor_ai, "mod_names": MOD_DISPLAY}

    # --- keypacks made by AI ---
    def ai_instructions(self):
        return AI_INSTRUCTIONS

    def copy_text(self, text):
        return set_clipboard(str(text))

    def parse_keypack_text(self, text):
        try:
            pack = parse_keypack(str(text))
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "name": pack["name"], "items": pack["mappings"]}

    def my_mappings(self):
        return [{**m, "label": display_label(m)} for m in self._cfg["mappings"]]

    def default_folder(self):
        return documents_folder()

    def choose_folder(self, start=""):
        import webview
        r = self._editor.create_file_dialog(webview.FileDialog.FOLDER, directory=start or documents_folder())
        return (r[0] if isinstance(r, (list, tuple)) else r) or None

    def export_keypack(self, name, filename, folder, rows, replace=False):
        try:
            fname = keypack_filename(filename)
            if not (isinstance(folder, str) and os.path.isdir(folder)):
                raise ValueError("Choose a folder that exists.")
            path = os.path.join(folder, fname)
            if os.path.exists(path) and not replace:
                return {"ok": False, "exists": True, "file": fname}
            name = write_keypack(path, name, rows)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except OSError as e:
            return {"ok": False, "error": f"Kemper couldn't save it there: {e.strerror or e}"}
        return {"ok": True, "path": path, "file": fname, "folder": folder, "name": name}

    def show_in_folder(self, path):
        if isinstance(path, str) and os.path.isfile(path):
            safely(show_file, path)

    def set_editor_dirty(self, dirty):
        self._editor_dirty = bool(dirty)

    def close_editor(self):
        self._editor_dirty = False
        if self._editor:
            self._editor.destroy()

    def _on_editor_closing(self):
        if self._quitting or not self._editor_dirty:
            return True
        # ask in the page; this handler runs on the UI thread, which evaluate_js waits for, so ask from another thread
        threading.Thread(target=lambda: self._editor and self._editor.evaluate_js("askClose()"), daemon=True).start()
        return False

    def _on_editor_closed(self):
        self._editor, self._editor_dirty = None, False

    # --- quick picker (like Win+V for the clipboard, but for your shortcuts) ---
    def _open_picker(self):
        if not self._picker:
            return
        if self._picker_open:  # the picker combo again closes it
            return self.close_picker(True)
        self._picker_target = safely(active_app)
        self._picker.evaluate_js("openPicker()")
        show_popup(self._picker, PICKER_TITLE)
        self._picker_open = True

    def _dark(self):
        a = self._cfg["appearance"]
        return a == "dark" or (a == "system" and os_is_dark())

    def picker_items(self):
        return {"items": [{"i": i, "text": m["text"], "label": display_label(m)} for i, m in enumerate(self._cfg["mappings"])],
                "dark": self._dark()}

    def close_picker(self, refocus=False):
        if not (self._picker and self._picker_open):
            return
        self._picker_open = False
        self._picker.hide()
        if refocus and self._picker_target:
            safely(activate, self._picker_target)

    def pick(self, i):
        maps, i = self._cfg["mappings"], int(i)
        if not 0 <= i < len(maps):
            return
        self.close_picker(True)
        time.sleep(0.15)  # let the target app take focus before typing into it
        type_text(maps[i]["text"])
        if self._on_fire:
            self._on_fire(maps[i])

    def _on_picker_closing(self):
        if self._quitting:
            return True
        self.close_picker(True)  # Alt+F4 on the popup just hides it
        return False

# ---------- single instance: the running Kemper listens on a local port for commands ----------
def claim_instance():
    srv = socket.socket()
    if IS_WIN:  # elsewhere a second bind on the same port already fails
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        srv.bind(("127.0.0.1", PORT))
    except OSError:
        srv.close()
        return None
    srv.listen()
    return srv

def serve(srv, api):
    def loop():
        while True:
            conn = srv.accept()[0]
            with conn:
                conn.settimeout(1)
                cmd = b""
                try:
                    while len(cmd) < 8192:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        cmd += chunk
                except OSError:
                    pass
            if cmd.startswith(b"keypack\n"):
                api._open_keypack(cmd[8:].decode("utf-8", "replace"))
            elif cmd == b"quit":
                api.quit()
            elif cmd == b"reload":
                api._reload()
            elif cmd in (b"show", b"") and api._window:
                api._window.show()
                api._window.restore()
            # b"ping" and anything else: the connection itself was the answer
    threading.Thread(target=loop, daemon=True).start()

def send_command(cmd):
    """Talk to the running Kemper. Returns False if it isn't running."""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=2) as s:
            s.sendall(cmd)
        return True
    except OSError:
        return False

# ---------- combos typed as text, e.g. "Alt+Shift+2" ----------
MOD_ALIASES = {"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift",
               "win": "Win", "windows": "Win", "meta": "Win", "super": "Win",
               "cmd": "Win", "command": "Win", "option": "Alt", "opt": "Alt"}  # Win is Cmd on a Mac, Super on Linux
NAMED_KEYS = {"space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
              "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D, "home": 0x24,
              "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
              "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}

def parse_combo(text):
    """'Alt+Shift+2' -> {"mods": ["Alt", "Shift"], "vk": 50, "key": "2"}. Raises ValueError with a readable message."""
    s = text.strip()
    parts = s[:-2].split("+") + ["+"] if s.endswith("++") else s.split("+")
    *mod_parts, key = [p.strip() for p in parts]
    if not key:
        raise ValueError(f"'{text}' is missing the key after the last +.")
    mods = []
    for p in mod_parts:
        m = MOD_ALIASES.get(p.lower())
        if not m:
            raise ValueError(f"Unknown modifier '{p}'. Use Ctrl, Alt, Shift or Win.")
        if m not in mods:
            mods.append(m)
    k = key.lower().replace(" ", "")  # "Page Up" and "Num 7" work too
    if k in NAMED_KEYS:
        vk = NAMED_KEYS[k]
    elif re.fullmatch(r"f([1-9]|1\d|2[0-4])", k):
        vk = 0x6F + int(k[1:])
    elif re.fullmatch(r"num[0-9]", k):
        vk = 0x60 + int(k[3:])
    elif len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key.upper())
    elif len(key) == 1 and (found := vk_for_char(key)):
        vk, needs_modifier = found
        if needs_modifier:  # the character itself needs Shift (or AltGr) on this keyboard layout
            raise ValueError(f"'{key}' isn't a key of its own on your keyboard. Write the key it's on, e.g. Shift+{key_name(vk)}.")
    else:
        raise ValueError(f"Unknown key '{key}'. Run --help to see the key names.")
    order = [n for n, _, _ in MODS]
    return {"mods": sorted(mods, key=order.index), "vk": vk, "key": key_name(vk)}

# ---------- CLI ----------
EXAMPLES = """\
combos:
  Join keys with +, e.g. Alt+2, Ctrl+Alt+E, Ctrl+Shift+Right.
  Modifiers: Ctrl, Alt, Shift, Win.
  Keys: A-Z, 0-9, F1-F24, Num0-Num9, Space, Enter, Tab, Esc, Backspace, Delete,
        Insert, Home, End, PageUp, PageDown, Left, Right, Up, Down,
        and punctuation keys like - = [ ] ; ' , . / `

examples:
  python kemper.pyw                           open the window
  python kemper.pyw --cli                     run in this terminal, no window
  python kemper.pyw --add "Alt+2" "²"         Alt+2 types ²
  python kemper.pyw --add "Alt+Shift+2" "₂"   Alt+Shift+2 types ₂
  python kemper.pyw --remove "Alt+2"
  python kemper.pyw --picker "Ctrl+Alt+P"     the quick picker opens with Ctrl+Alt+P
  python kemper.pyw --keys
  python kemper.pyw --doctor
"""

def build_parser():
    p = argparse.ArgumentParser(
        prog="python kemper.pyw", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=EXAMPLES,
        description="Kemper (Key Mapper): press a key combo, get a character or text typed, in any app.\n"
                    "With no options, Kemper opens its window.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--cli", action="store_true", help="run in this terminal with no window; logs every shortcut you use (Ctrl+C stops)")
    g.add_argument("--keys", action="store_true", help="list your shortcuts")
    g.add_argument("--add", nargs=2, metavar=("COMBO", "TEXT"), help='add a shortcut, e.g. --add "Alt+2" "²"')
    g.add_argument("--remove", metavar="COMBO", help='remove a shortcut, e.g. --remove "Alt+2"')
    g.add_argument("--picker", metavar="COMBO|on|off", help='set the quick picker\'s combo, e.g. --picker "Ctrl+Alt+K", or turn it on/off')
    g.add_argument("--activate", action="store_true", help="turn shortcuts on")
    g.add_argument("--deactivate", action="store_true", help="turn every shortcut off without quitting Kemper")
    g.add_argument("--desktop", choices=["on", "off"],
                   help="put a Kemper shortcut, with Kemper's icon, on the desktop, or remove it (Windows, Linux)")
    g.add_argument("--status", action="store_true", help="show whether Kemper is running and how it is set up")
    g.add_argument("--doctor", action="store_true", help="check for problems and say how to fix each one")
    g.add_argument("--show", action="store_true", help="open the window (starts Kemper if it isn't running)")
    g.add_argument("--quit", action="store_true", help="stop the running Kemper, window or --cli")
    g.add_argument("--autostart", choices=["on", "off"],
                   help="start Kemper when you sign in, or stop doing so (same as the switch in the window)")
    g.add_argument("--uninstall", action="store_true",
                   help="remove Kemper from this PC: stop it, remove it from startup, delete your settings and this file")
    g.add_argument("--ai-instructions", action="store_true",
                   help="print instructions that let an AI chat (ChatGPT, Claude, …) write keypacks for you")
    g.add_argument("--keypack", metavar="FILE", help="open a keypack (.kmppck) and ask whether to import it, like double-clicking one")
    g.add_argument("--hidden", action="store_true", help="open with the window hidden (used when you sign in)")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation (for --uninstall)")
    p.add_argument("-v", "--version", action="version", version=f"Kemper {VERSION}")
    return p

def fail(msg):
    print(f"kemper: {msg}", file=sys.stderr)
    sys.exit(1)

def one_line(text):
    return text.replace("\r\n", "\n").replace("\n", "⏎")

def change_config(change):
    """Load, edit, validate and save the settings, then tell a running Kemper to reload them."""
    cfg = load()
    change(cfg)
    try:
        cfg["picker"] = clean_picker(cfg["picker"])
        cfg["mappings"] = clean_mappings(cfg["mappings"], cfg["picker"])
    except ValueError as e:
        fail(f"{e} Nothing was saved. Run --doctor for details.")
    save(cfg)
    if send_command(b"reload"):
        print("The running Kemper picked up the change.")

def picker_line(cfg):
    p = cfg["picker"]
    return f"Quick picker: {combo_label(p)}" if p["enabled"] else "Quick picker: off"

def cmd_keys():
    cfg = load()
    maps = cfg["mappings"]
    if not maps:
        print('No shortcuts yet. Add one with:  python kemper.pyw --add "Alt+2" "²"')
        print(picker_line(cfg))
        return
    dup = find_conflicts(maps)
    width = max(len(combo_label(m)) for m in maps)
    for m in maps:
        flag = "   ✗ same keys as another shortcut" if combo_id(m) in dup else ""
        print(f"  {combo_label(m):<{width}}  →  {one_line(m['text'])}{flag}")
    print(f"\n{len(maps)} shortcut(s), {'active' if cfg['active'] else 'deactivated'}. {picker_line(cfg)}")

def cmd_add(combo, text):
    try:
        m = parse_combo(combo)
    except ValueError as e:
        fail(e)
    if not text:
        fail("The text can't be empty.")
    m["text"] = text

    def change(cfg):
        p = cfg["picker"]
        if p["enabled"] and combo_id(p) == combo_id(m):
            fail(f"{combo_label(m)} opens the quick picker. Use other keys, or move the picker first:  "
                 f'python kemper.pyw --picker "Ctrl+Alt+P"')
        for old in cfg["mappings"]:
            if combo_id(old) == combo_id(m):
                fail(f"{combo_label(m)} already types {one_line(old['text'])}. "
                     f'Remove it first:  python kemper.pyw --remove "{combo}"')
        cfg["mappings"].append(m)
    change_config(change)
    print(f"Added {combo_label(m)}  →  {one_line(text)}")

def cmd_remove(combo):
    try:
        target = combo_id(parse_combo(combo))
    except ValueError as e:
        fail(e)

    def change(cfg):
        keep = [m for m in cfg["mappings"] if combo_id(m) != target]
        if len(keep) == len(cfg["mappings"]):
            fail(f"No shortcut uses {combo}. See them with:  python kemper.pyw --keys")
        cfg["mappings"] = keep
    change_config(change)
    print(f"Removed {combo}.")

def cmd_picker(value):
    v = value.strip().lower()

    def change(cfg):
        if v in ("on", "off"):
            cfg["picker"]["enabled"] = v == "on"
            return
        try:
            cfg["picker"].update(parse_combo(value), enabled=True)
        except ValueError as e:
            fail(e)
    change_config(change)
    print(picker_line(load()))

def cmd_set_active(on):
    change_config(lambda cfg: cfg.update(active=on))
    print("Shortcuts are on." if on else "Shortcuts are off. Turn them back on with:  python kemper.pyw --activate")

def cmd_desktop(on):
    if not CAN_DESKTOP:
        fail("Desktop shortcuts aren't available on macOS. Start Kemper with:  python3 kemper.pyw")
    try:
        set_desktop(on)
    except OSError as e:
        fail(f"Couldn't create the desktop shortcut: {e}")
    print(f"Added Kemper to your desktop ({desktop_path()})." if on else "Removed Kemper from your desktop.")

def cmd_status():
    cfg = load()
    running = send_command(b"ping")
    print(f"Kemper {VERSION}")
    print(f"  Running:             {'yes' if running else 'no'}")
    print(f"  Shortcuts:           {len(cfg['mappings'])} ({'active' if cfg['active'] else 'deactivated'})")
    print(f"  {picker_line(cfg).replace(': ', ':        ')}")
    print(f"  {('Start with Windows' if IS_WIN else 'Start at login') + ':':<20} {'on' if startup_enabled() else 'off'}")
    if CAN_DESKTOP:
        print(f"  Desktop shortcut:    {'yes' if desktop_enabled() else 'no'}")
    if CAN_APP_MENU:
        print(f"  {('In the Start menu' if IS_WIN else 'In the app menu') + ':':<20} {'yes' if app_menu_registered() else 'no'}")
    print(f"  System:              {OS_NAME}")
    print(f"  Settings file:       {CONFIG}")
    print(f"  Program file:        {os.path.abspath(__file__)}")

def cmd_doctor():
    levels = []

    def check(level, msg):  # 0 ok, 1 warning, 2 problem
        levels.append(level)
        print(f"  {'✓!✗'[level]}  {msg}")

    print(f"Kemper {VERSION} doctor\n")
    v = sys.version_info
    check(0 if v >= (3, 10) else 2, f"Python {v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 10) else " (Kemper needs 3.10 or newer)"))
    try:
        import importlib.metadata
        check(0, f"pywebview {importlib.metadata.version('pywebview')} is installed (needed for the window)")
    except importlib.metadata.PackageNotFoundError:
        check(1, "pywebview isn't installed, so only --cli works. Fix:  python -m pip install pywebview")
    platform_checks(check)

    cfg = load()
    if not os.path.exists(CONFIG):
        check(0, "No settings file yet. It's created the first time you save.")
    else:
        try:
            with open(CONFIG, encoding="utf-8") as f:
                json.load(f)
            clean_mappings(cfg["mappings"], clean_picker(cfg["picker"]))
            check(0, f"{len(cfg['mappings'])} shortcut(s) saved in {CONFIG}")
        except ValueError as e:
            check(2, f"Settings file has a problem: {e} ({CONFIG})")
        check(0 if cfg["active"] else 1, "Shortcuts are active" if cfg["active"] else
              "Kemper is deactivated, so shortcuts do nothing. Fix:  python kemper.pyw --activate")

    running = send_command(b"ping")
    check(0 if running else 1, "Kemper is running" if running else
          f"Kemper isn't running, so shortcuts do nothing. Start it:  {'pythonw' if IS_WIN else 'python3'} kemper.pyw  (or --cli)")

    sv = startup_value()
    if sv is None:
        check(1, "Kemper doesn't start when you sign in. Fix:  python kemper.pyw --autostart on")
    elif sv == startup_cmd():
        check(0, "Starts when you sign in")
    else:
        check(2, "The startup entry points to a different place (was Kemper moved?). Fix:  python kemper.pyw --autostart on")

    if CAN_KEYPACK_FILES:
        linked = keypacks_registered()
        check(0 if linked else 1, "Keypack files (.kmppck) open in Kemper" if linked else
              "Keypack files (.kmppck) aren't linked to Kemper yet. Fix: open Kemper's window once")
    if CAN_APP_MENU:
        menu = "the Start menu" if IS_WIN else "the app menu"
        listed = app_menu_registered()
        check(0 if listed else 1, f"Kemper is in {menu}, so searching for it finds it" if listed else
              f"Kemper isn't in {menu} yet, so searching for it won't find it. Fix: open Kemper's window once")

    if running:
        combos = cfg["mappings"] + ([cfg["picker"]] if cfg["picker"]["enabled"] else [])
        swallowed = [combo_label(m) for m in combos if combo_id(m) in input_language_hotkeys()]
        if swallowed:  # these never reach Kemper, running or not
            check(2, "Windows swallows these before Kemper sees them: " + ", ".join(swallowed) + SWALLOWED_HINT)
        else:
            check(0, "Skipped the hotkey check because the running Kemper is holding them")
    else:
        combos = cfg["mappings"] + ([cfg["picker"]] if cfg["picker"]["enabled"] else [])
        taken = hotkeys_taken(combos)
        if taken is not None:
            check(2 if taken else 0, ("Already used by another app: " + ", ".join(taken) + ". Pick different keys for these.")
                  if taken else "No other app is using your combos")

    print("\nAll good." if max(levels) == 0 else "\nDone. See the ! and ✗ lines above.")
    if 2 in levels:
        sys.exit(1)

def run_cli():
    srv = claim_instance()
    if not srv:
        fail("Kemper is already running. Stop it first with:  python kemper.pyw --quit")

    def fired(m):
        print(f"  {time.strftime('%H:%M:%S')}  {combo_label(m)}  →  {one_line(m['text'])}", flush=True)

    def reloaded():
        n, on = len(api._cfg["mappings"]), api._cfg["active"]
        print(f"  Settings changed: {n} shortcut(s), {'active' if on else 'deactivated'}.", flush=True)

    api = Api(on_fire=fired, on_reload=reloaded)
    serve(srv, api)
    cfg = api._cfg
    print(f"Kemper {VERSION} is running in this terminal (no window).")
    if cfg["active"]:
        print(f"  {len(cfg['mappings'])} shortcut(s) active. Each one shows up here when you use it.")
    else:
        print("  Kemper is deactivated, so shortcuts do nothing. Turn them on with:  python kemper.pyw --activate")
    if api._notice:
        print("  " + api._notice)
    if cfg["picker"]["enabled"]:
        print("  The quick picker needs the window version, so it's off in this mode.")
    print("  Press Ctrl+C to stop.\n", flush=True)
    try:
        while not api._done.wait(0.5):  # short waits keep Ctrl+C responsive
            pass
    except KeyboardInterrupt:
        pass
    api._stop()
    print("Kemper stopped.")

def start_gui_process():
    quiet = {} if IS_WIN else {"start_new_session": True, "stdin": subprocess.DEVNULL,
                                   "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    subprocess.Popen([pythonw(), os.path.abspath(__file__)], close_fds=True, **quiet)

def cmd_show():
    if send_command(b"show"):
        return
    start_gui_process()
    print("Started Kemper.")

def cmd_quit():
    print("Kemper stopped." if send_command(b"quit") else "Kemper isn't running.")

def cmd_autostart(on):
    set_startup(on)
    print("Kemper will start when you sign in." if on else "Kemper won't start when you sign in anymore.")

def cmd_uninstall(yes):
    me = os.path.abspath(__file__)
    if not yes:
        print("This stops Kemper, removes it from startup and the desktop, deletes your shortcuts and settings,")
        print("and deletes")
        print(f"  {me}")
        try:
            answer = input("Uninstall Kemper? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled. Nothing was changed.")
            return
    if send_command(b"quit"):
        for _ in range(30):  # wait for it to exit so it can't rewrite the settings after we delete them
            if not send_command(b"ping"):
                break
            time.sleep(0.2)
        print("Stopped the running Kemper.")
    set_startup(False)
    print("Removed Kemper from startup.")
    if desktop_enabled():
        set_desktop(False)
        print("Removed the desktop shortcut.")
    if CAN_KEYPACK_FILES:
        unregister_keypacks()
        print("Unlinked .kmppck keypack files from Kemper.")
    if CAN_APP_MENU:
        unregister_app_menu()
        print("Removed Kemper from the Start menu." if IS_WIN else "Removed Kemper from the app menu.")
    folder = os.path.dirname(CONFIG)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
        print(f"Deleted your shortcuts and settings ({folder}).")
    os.remove(me)
    print(f"Deleted {me}.\nKemper is uninstalled.")

def run_gui(hidden, keypack=None):
    srv = claim_instance()
    if not srv:  # already running: hand over to it
        safely(allow_foreground)
        send_command(b"keypack\n" + keypack.encode("utf-8") if keypack else b"show")
        return
    try:
        import webview  # imported here so the CLI works without it
    except ImportError:
        if hidden:  # started with Windows but can't draw a window: still run the shortcuts
            api = Api()
            serve(srv, api)
            api._done.wait()
            return
        safely(alert, "Kemper's window needs pywebview. Install it with:\n\n    python -m pip install pywebview\n\n"
                      "Or use Kemper without a window:\n\n    python kemper.pyw --cli\n\nhttps://kemper.talken.in")
        return
    api = Api()
    api._pending_keypack = keypack
    serve(srv, api)
    for register in (register_keypacks, register_app_menu):
        try:
            register()
        except OSError:
            pass  # Kemper still works; only double-clicking keypacks, or finding it in Start, won't
    cfg = api._cfg
    dark = cfg["appearance"] == "dark" or (cfg["appearance"] == "system" and os_is_dark())
    win = webview.create_window(APP, html=UI_HTML, js_api=api, width=540, height=680, min_size=(440, 480),
                                hidden=hidden and not keypack, background_color="#000000" if dark else "#F2F2F7", text_select=True)
    api._window = win
    win.events.closing += api._on_closing
    win.events.shown += lambda: dark_title_bar(dark)
    picker = webview.create_window(PICKER_TITLE, html=PICKER_HTML, js_api=api, width=380, height=460, hidden=True,
                                   frameless=True, easy_drag=False, on_top=True, resizable=False,
                                   background_color="#1C1C1E" if dark else "#FFFFFF", text_select=True)
    api._picker = picker
    picker.events.closing += api._on_picker_closing
    api._stop()  # restart the hotkeys now that the picker exists, so its combo gets registered
    api._start()
    safely(app_identity)
    webview.start(icon=icon_path())

def main():
    for stream in (sys.stdout, sys.stderr):
        if stream:  # None under pythonw
            stream.reconfigure(encoding="utf-8", errors="replace")
    a = build_parser().parse_args()
    if a.cli:
        run_cli()
    elif a.keys:
        cmd_keys()
    elif a.add:
        cmd_add(*a.add)
    elif a.remove:
        cmd_remove(a.remove)
    elif a.picker:
        cmd_picker(a.picker)
    elif a.activate or a.deactivate:
        cmd_set_active(a.activate)
    elif a.desktop:
        cmd_desktop(a.desktop == "on")
    elif a.status:
        cmd_status()
    elif a.doctor:
        cmd_doctor()
    elif a.show:
        cmd_show()
    elif a.quit:
        cmd_quit()
    elif a.autostart:
        cmd_autostart(a.autostart == "on")
    elif a.uninstall:
        cmd_uninstall(a.yes)
    elif a.ai_instructions:
        print(AI_INSTRUCTIONS)
    elif a.keypack:
        run_gui(False, os.path.abspath(a.keypack))
    else:
        run_gui(a.hidden)

# ---------- the window's page (HTML/CSS/JS), kept here so Kemper stays a single file ----------
UI_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kemper</title>
<style>
  :root {
    --bg: #F2F2F7; --card: #FFFFFF; --sep: rgba(60,60,67,.18); --text: #1C1C1E; --sub: #8E8E93;
    --blue: #007AFF; --red: #FF3B30; --orange: #FF9500; --orange-bg: rgba(255,149,0,.12); --green-bg: rgba(52,199,89,.14); --red-bg: rgba(255,59,48,.10); --green: #34C759;
    --pill: #EEEEF3; --pill-text: #1C1C1E; --off: #E9E9EA; --seg: rgba(118,118,128,.12); --seg-on: #FFFFFF;
    --bar: rgba(242,242,247,.82); --shadow: 0 1px 2px rgba(0,0,0,.04);
    color-scheme: light;
  }
  :root.dark {
    --bg: #000000; --card: #1C1C1E; --sep: rgba(84,84,88,.6); --text: #FFFFFF; --sub: #8E8E93;
    --blue: #0A84FF; --red: #FF453A; --orange: #FF9F0A; --orange-bg: rgba(255,159,10,.16); --green-bg: rgba(48,209,88,.16); --red-bg: rgba(255,69,58,.16); --green: #30D158;
    --pill: #2C2C2E; --pill-text: #FFFFFF; --off: #39393D; --seg: rgba(118,118,128,.24); --seg-on: #636366;
    --bar: rgba(0,0,0,.78); --shadow: none;
    color-scheme: dark;
  }
  * { box-sizing: border-box; }
  button, input { font-family: inherit; }
  html, body { margin: 0; height: 100%; }
  body {
    background: var(--bg); color: var(--text);
    font: 15px/1.35 "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
    user-select: none; -webkit-user-select: none;
    display: flex; flex-direction: column; overflow: hidden;
    transition: background-color .25s ease, color .25s ease;
  }
  main { flex: 1; overflow-y: auto; padding: 22px 20px 24px; scrollbar-gutter: stable; }
  main::-webkit-scrollbar { width: 10px; }
  main::-webkit-scrollbar-thumb { background: var(--sep); border-radius: 10px; border: 3px solid var(--bg); }

  header { display: flex; align-items: baseline; justify-content: space-between; margin: 0 4px 18px; }
  h1 { font: 700 32px/1.1 "Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif; margin: 0; letter-spacing: -.5px; }
  .link { background: none; border: 0; padding: 4px 6px; font: inherit; color: var(--red); cursor: pointer; border-radius: 8px; }
  .link:hover { background: var(--red-bg); }
  .actions { display: flex; gap: 4px; }
  #toggle { color: var(--orange); }
  #toggle:hover { background: var(--orange-bg); }
  #toggle.go { color: var(--green); }
  #toggle.go:hover { background: var(--green-bg); }
  #list { transition: opacity .25s ease; }
  body.off #list { opacity: .5; }

  .section-title { font-size: 12.5px; letter-spacing: .3px; text-transform: uppercase; color: var(--sub); margin: 22px 16px 7px; }
  .section-foot { font-size: 12.5px; color: var(--sub); margin: 7px 16px 0; }
  .card { background: var(--card); border-radius: 12px; overflow: hidden; box-shadow: var(--shadow); transition: background-color .25s ease; }
  .row { display: flex; align-items: center; gap: 10px; min-height: 50px; padding: 8px 14px 8px 16px; position: relative; transition: background-color .2s ease; }
  .row + .row::before { content: ""; position: absolute; top: 0; left: 16px; right: 0; height: 1px; background: var(--sep); transform: scaleY(.5); transform-origin: top; }
  .row .label { flex: 1; min-width: 0; }

  /* iOS switch */
  .switch { position: relative; width: 51px; height: 31px; flex: none; }
  .switch input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: pointer; z-index: 1; }
  .switch span { position: absolute; inset: 0; border-radius: 31px; background: var(--off); transition: background-color .25s ease; }
  .switch span::after { content: ""; position: absolute; top: 2px; left: 2px; width: 27px; height: 27px; border-radius: 50%; background: #fff;
    box-shadow: 0 3px 8px rgba(0,0,0,.15), 0 1px 1px rgba(0,0,0,.16); transition: transform .25s cubic-bezier(.3,.7,.4,1); }
  .switch input:checked + span { background: var(--green); }
  .switch input:checked + span::after { transform: translateX(20px); }
  .switch input:focus-visible + span { outline: 2px solid var(--blue); outline-offset: 2px; }

  /* segmented control */
  .seg { display: flex; background: var(--seg); border-radius: 9px; padding: 2px; flex: none; }
  .seg button { border: 0; background: none; color: var(--text); font-size: 13px; font-weight: 500; line-height: 1; padding: 7px 12px; border-radius: 7px; cursor: pointer; transition: background-color .2s ease, box-shadow .2s ease; }
  .seg button.on { background: var(--seg-on); box-shadow: 0 2px 6px rgba(0,0,0,.12); }

  /* shortcut rows */
  .pill { flex: none; width: 168px; height: 34px; border: 0; border-radius: 9px; background: var(--pill); color: var(--pill-text);
    font-size: 13px; font-weight: 600; line-height: 34px; padding: 0 10px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    transition: background-color .2s ease, color .2s ease, transform .1s ease; }
  .pill:active { transform: scale(.97); }
  .pill.empty { color: var(--blue); }
  .pill.recording { background: var(--blue); color: #fff; animation: pulse 1.2s ease-in-out infinite; }
  .pill.bad { background: var(--red); color: #fff; }
  .pill:disabled { opacity: .4; cursor: default; }
  @keyframes pulse { 50% { opacity: .72; } }
  .text { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--text); font-size: 20px;
    padding: 6px 0; user-select: text; -webkit-user-select: text; }
  .text::placeholder { color: var(--sub); }
  .row.bad { background: var(--red-bg); }
  .del { flex: none; width: 24px; height: 24px; border-radius: 50%; border: 0; background: var(--red); color: #fff; cursor: pointer;
    display: grid; place-items: center; opacity: .9; transition: opacity .15s ease, transform .1s ease; }
  .del:hover { opacity: 1; }
  .del:active { transform: scale(.9); }
  .del::before { content: ""; width: 10px; height: 2px; border-radius: 1px; background: #fff; }
  .add { width: 100%; border: 0; background: none; color: var(--blue); font: inherit; text-align: left; padding: 0 16px; min-height: 50px; cursor: pointer;
    display: flex; align-items: center; gap: 10px; position: relative; }
  .add:hover { background: var(--seg); }
  .card .row + .add::before { content: ""; position: absolute; top: 0; left: 16px; right: 0; height: 1px; background: var(--sep); transform: scaleY(.5); transform-origin: top; }
  .add i { width: 22px; height: 22px; border-radius: 50%; background: var(--green); position: relative; flex: none; }
  .add i::before, .add i::after { content: ""; position: absolute; left: 6px; top: 10px; width: 10px; height: 2px; border-radius: 1px; background: #fff; }
  .add i::after { transform: rotate(90deg); }

  footer { flex: none; display: flex; align-items: center; gap: 14px; padding: 12px 20px 16px; background: var(--bar);
    backdrop-filter: saturate(180%) blur(20px); border-top: 1px solid var(--sep); }
  #status { flex: 1; min-width: 0; font-size: 13px; color: var(--sub); transition: color .2s ease; }
  #status.err { color: var(--red); }
  #save { flex: none; border: 0; border-radius: 12px; background: var(--blue); color: #fff; font-size: 15px; font-weight: 600;
    padding: 11px 30px; cursor: pointer; transition: opacity .2s ease, transform .1s ease, background-color .2s ease; }
  #save:active:not(:disabled) { transform: scale(.97); }
  #save:disabled { opacity: .35; cursor: default; }
  button:focus-visible, .text:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }

  /* rows that open something, like iOS settings */
  .navrow { width: 100%; border: 0; background: none; color: var(--blue); font: inherit; text-align: left; padding: 0 16px;
    min-height: 50px; cursor: pointer; display: flex; align-items: center; gap: 10px; position: relative; }
  .navrow:hover { background: var(--seg); }
  .navrow span { flex: 1; }
  .navrow + .navrow::before { content: ""; position: absolute; top: 0; left: 16px; right: 0; height: 1px; background: var(--sep); transform: scaleY(.5); transform-origin: top; }
  .chev { width: 8px; height: 8px; border-right: 2px solid var(--sub); border-top: 2px solid var(--sub); transform: rotate(45deg); opacity: .6; margin-right: 4px; }

  /* sheets: iOS-style dialogs over the page */
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.32); display: grid; place-items: center; padding: 20px; z-index: 10;
    opacity: 0; transition: opacity .2s ease; }
  .overlay.show { opacity: 1; }
  .overlay[hidden], [hidden] { display: none !important; }
  .sheet { background: var(--card); color: var(--text); border-radius: 16px; width: min(520px, 100%); max-height: calc(100vh - 40px);
    display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 20px 60px rgba(0,0,0,.3);
    transform: translateY(12px) scale(.98); transition: transform .22s cubic-bezier(.3,.7,.4,1); }
  .sheet.wide { width: min(700px, 100%); }
  .overlay.show .sheet { transform: none; }
  .shead { padding: 20px 20px 12px; }
  .shead h2 { margin: 0; font-size: 19px; font-weight: 700; overflow-wrap: anywhere; }
  .shead .sub { color: var(--sub); font-size: 13px; margin-top: 4px; overflow-wrap: anywhere; }
  .sbody { padding: 0 20px; overflow-y: auto; min-height: 0; flex: 1; }
  .sbody p { margin: 0 0 6px; font-size: 14px; }
  .sfoot { display: flex; gap: 10px; justify-content: flex-end; align-items: center; padding: 14px 20px 18px; }
  .note { flex: 1; font-size: 12.5px; color: var(--sub); }
  .note.err { color: var(--red); }
  .note.warn { color: var(--orange); }
  .btn { border: 0; border-radius: 10px; padding: 9px 18px; font-size: 14px; font-weight: 600; cursor: pointer; background: var(--seg); color: var(--text); flex: none; }
  .btn.primary { background: var(--blue); color: #fff; }
  .btn.danger { background: var(--red); color: #fff; }
  .btn:disabled { opacity: .4; cursor: default; }
  .choice { width: 100%; text-align: left; border: 0; background: var(--bg); border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; cursor: pointer; color: var(--text); display: block; }
  .choice:hover { background: var(--seg); }
  .choice b { display: block; font-size: 15px; color: var(--blue); margin-bottom: 2px; }
  .choice small { color: var(--sub); font-size: 12.5px; }
  .plist { background: var(--bg); border-radius: 12px; overflow: hidden; }
  .prow { display: flex; align-items: center; gap: 12px; padding: 8px 12px; position: relative; }
  .prow + .prow::before { content: ""; position: absolute; top: 0; left: 12px; right: 0; height: 1px; background: var(--sep); transform: scaleY(.5); transform-origin: top; }
  .prow.bad { background: var(--red-bg); }
  .prow .pill { width: 150px; height: 30px; line-height: 30px; text-align: center; cursor: default; }
  .ptext { flex: 1; min-width: 0; font-size: 18px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .issue { flex: none; max-width: 42%; font-size: 11.5px; font-weight: 600; text-align: right; }
  .issue.bad { color: var(--red); }
  .issue.warn { color: var(--orange); }
  .issue.same { color: var(--sub); }
  .field { margin-bottom: 14px; }
  .field > span { display: block; font-size: 12px; color: var(--sub); margin: 0 0 6px 2px; text-transform: uppercase; letter-spacing: .3px; }
  .field small { display: block; font-size: 12px; color: var(--sub); margin: 6px 2px 0; }
  .input { width: 100%; min-width: 0; border: 0; outline: 0; border-radius: 10px; background: var(--bg); color: var(--text); font-size: 15px;
    padding: 10px 12px; user-select: text; -webkit-user-select: text; }
  .input:focus-visible { outline: 2px solid var(--blue); }
  .suffix, .folder { display: flex; align-items: center; gap: 8px; }
  .area { width: 100%; min-height: 120px; border: 0; outline: 0; border-radius: 10px; background: var(--bg); color: var(--text); padding: 10px 12px;
    font: 12.5px/1.45 "Cascadia Mono", Consolas, monospace; resize: vertical; user-select: text; -webkit-user-select: text; }
  .area:focus-visible { outline: 2px solid var(--blue); }
  .step { display: flex; gap: 12px; margin-bottom: 16px; }
  .step .n { flex: none; width: 24px; height: 24px; border-radius: 50%; background: var(--blue); color: #fff; font-size: 13px; font-weight: 700;
    display: grid; place-items: center; margin-top: 1px; }
  .step .body { flex: 1; min-width: 0; }
  .step .body > b { display: block; font-size: 14.5px; margin-bottom: 3px; }
  .step .body > small { display: block; color: var(--sub); font-size: 12.5px; }
  .btns { display: flex; gap: 8px; margin-top: 9px; }
  .suffix em { color: var(--sub); font-style: normal; flex: none; }
  .folder .path { flex: 1; min-width: 0; background: var(--bg); border-radius: 10px; padding: 10px 12px; font-size: 13px; color: var(--sub);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
</head>
<body>
<main>
  <header>
    <h1>Shortcuts</h1>
    <div class="actions">
      <button class="link" id="toggle"></button>
      <button class="link" id="quit" title="Close Kemper. Shortcuts stop until you open it again.">Quit</button>
    </div>
  </header>

  <div class="section-title">General</div>
  <div class="card">
    <div class="row">
      <div class="label" id="startupLabel">Start with Windows</div>
      <label class="switch"><input type="checkbox" id="startup" aria-label="Start with Windows"><span></span></label>
    </div>
    <div class="row" id="desktopRow">
      <div class="label">Desktop shortcut</div>
      <label class="switch"><input type="checkbox" id="desktop" aria-label="Desktop shortcut"><span></span></label>
    </div>
    <div class="row">
      <div class="label">Appearance</div>
      <div class="seg" id="appearance" role="group" aria-label="Appearance">
        <button data-v="system">System</button><button data-v="light">Light</button><button data-v="dark">Dark</button>
      </div>
    </div>
  </div>

  <div class="section-title">Quick Picker</div>
  <div class="card">
    <div class="row">
      <div class="label">Quick picker</div>
      <label class="switch"><input type="checkbox" id="pickerOn" aria-label="Quick picker"><span></span></label>
    </div>
    <div class="row" id="pickerRow">
      <div class="label">Open it with</div>
      <button class="pill" id="pickerPill"></button>
    </div>
  </div>
  <div class="section-foot" id="pickerFoot">Press it in any app to see all your shortcuts and pick one, like Win + V does for the clipboard.</div>

  <div class="section-title">Key → Text</div>
  <div class="card" id="list"></div>
  <div class="section-foot" id="hint">Click a key box, then press the combo, like Alt + 2. Paste or type the text it should produce, like ².</div>

  <div class="section-title">Keypacks</div>
  <div class="card">
    <button class="navrow" id="kpCreate"><span>Create a keypack</span><i class="chev"></i></button>
    <button class="navrow" id="kpImport"><span>Import a keypack…</span><i class="chev"></i></button>
    <button class="navrow" id="kpMarket"><span>Browse the Marketplace</span><i class="chev"></i></button>
  </div>
  <div class="section-foot" id="kpFoot">Keypacks are sets of shortcuts in .kmppck files that you can share. Double-click one to import it.</div>
</main>
<footer>
  <div id="status"></div>
  <button id="save" disabled>Save</button>
</footer>
<div class="overlay" id="overlay" hidden><div class="sheet" id="sheet" role="dialog" aria-modal="true"></div></div>

<script>
/*SHARED_JS*/
let api, rows = [], picker = null, saved = "", notice = "", recording = null, appearance = "system", active = true;
const $ = s => document.querySelector(s);
const ORDER = ["Ctrl", "Alt", "Shift", "Win"];
const MOD_KEYS = ["Control", "Alt", "Shift", "Meta", "AltGraph", "OS"];
const media = matchMedia("(prefers-color-scheme: dark)");

const id = r => [...r.mods].sort().join("+") + "|" + r.vk;
let MODN = {};  // Kemper's modifier names in this system's words: Cmd and Option on a Mac, Super on Linux
const label = r => [...r.mods].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b)).map(m => MODN[m] || m).concat(r.key).join(" + ");
const snapshot = () => JSON.stringify({ rows, picker });
const conflicts = () => {
  const n = {};
  rows.filter(r => r.vk).concat(picker?.enabled ? [picker] : []).forEach(r => n[id(r)] = (n[id(r)] || 0) + 1);
  return new Set(Object.keys(n).filter(k => n[k] > 1));
};

function render() {
  const list = $("#list");
  list.replaceChildren();
  rows.forEach((r, i) => {
    const row = document.createElement("div");
    row.className = "row";
    const pill = document.createElement("button");
    pill.className = "pill";
    pill.onclick = e => { e.stopPropagation(); recording === null ? startRecording(i) : stopRecording(null); };
    const text = document.createElement("input");
    text.className = "text";
    text.placeholder = "Text to type";
    text.value = r.text;
    text.spellcheck = false;
    text.oninput = () => { r.text = text.value; validate(); };
    const del = document.createElement("button");
    del.className = "del";
    del.title = "Delete shortcut";
    del.setAttribute("aria-label", "Delete shortcut");
    del.onclick = () => { if (recording === null) { rows.splice(i, 1); render(); } };
    row.append(pill, text, del);
    list.append(row);
  });
  const add = document.createElement("button");
  add.className = "add";
  add.innerHTML = "<i></i>Add Shortcut";
  add.onclick = e => {
    e.stopPropagation(); // the page-level click handler would cancel the recording we start here
    rows.push({ mods: [], vk: 0, key: "", text: "" });
    render();
    startRecording(rows.length - 1);
    $("main").scrollTo({ top: 1e6, behavior: "smooth" });
  };
  list.append(add);
  validate();
}

function validate() {
  const dup = conflicts();
  [...$("#list").querySelectorAll(".row")].forEach((row, i) => {
    const r = rows[i], pill = row.querySelector(".pill"), bad = r.vk && dup.has(id(r));
    row.classList.toggle("bad", !!bad);
    pill.className = "pill" + (recording === i ? " recording" : bad ? " bad" : r.vk ? "" : " empty");
    pill.textContent = recording === i ? "Press keys…" : r.vk ? label(r) : "Set keys";
    pill.title = recording === i ? "Press a key combo · Esc to cancel" : "Click to change";
  });
  if (picker) {
    const pill = $("#pickerPill"), bad = picker.enabled && dup.has(id(picker));
    $("#pickerRow").classList.toggle("bad", bad);
    $("#pickerOn").checked = picker.enabled;
    pill.disabled = !picker.enabled;
    pill.className = "pill" + (recording === "picker" ? " recording" : bad ? " bad" : "");
    pill.textContent = recording === "picker" ? "Press keys…" : label(picker);
    pill.title = recording === "picker" ? "Press a key combo · Esc to cancel" : "Click to change";
  }
  let msg, ok = false, err = false;
  if (recording !== null) msg = "Press the combo now. Esc cancels.";
  else if (dup.size) { msg = "Two or more shortcuts use the same keys. Change the red ones before saving."; err = true; }
  else if (rows.some(r => !r.vk || !r.text)) msg = "Every shortcut needs both keys and text.";
  else if (snapshot() === saved && !active) msg = "Kemper is deactivated. Shortcuts won't type anything until you activate it.";
  else if (snapshot() === saved) { msg = notice || "All changes saved. Shortcuts are active."; err = !!notice; }
  else { msg = lastImport || "You have unsaved changes."; ok = true; }
  $("#status").textContent = msg;
  $("#status").classList.toggle("err", err);
  $("#save").disabled = !ok;
}

// Minecraft-style key capture
async function startRecording(i) {
  if (recording !== null) return;
  document.activeElement?.blur();
  recording = i;
  validate();
  await api.capture(true);
}
async function stopRecording(update) {
  const i = recording;
  recording = null;
  if (update) Object.assign(i === "picker" ? picker : rows[i], update);
  await api.capture(false);
  validate();
}
document.addEventListener("keydown", async e => {
  if (sheetOpen) {
    if (e.key === "Escape") { e.preventDefault(); closeSheet(); }
    return;
  }
  if (recording === null) {
    if (e.key === "s" && e.ctrlKey && !$("#save").disabled) { e.preventDefault(); $("#save").click(); }
    return;
  }
  e.preventDefault();
  e.stopPropagation();
  if (MOD_KEYS.includes(e.key)) return; // wait for the actual key
  const mods = [];
  if (e.ctrlKey) mods.push("Ctrl");
  if (e.altKey) mods.push("Alt");
  if (e.shiftKey) mods.push("Shift");
  if (e.metaKey) mods.push("Win");
  if (e.key === "Escape" && !mods.length) return stopRecording(null);
  const vk = e.keyCode; // on Windows this is the virtual-key code
  const i = recording;
  await stopRecording({ mods, vk, key: await api.key_name(vk) });
  const input = $("#list").querySelectorAll(".text")[i];
  if (input && !input.value) input.focus();
}, true);
document.addEventListener("click", () => { if (recording !== null) stopRecording(null); });
window.addEventListener("blur", () => { if (recording !== null) stopRecording(null); });

$("#save").onclick = async () => {
  const res = await api.save(rows, picker);
  if (!res.ok) { $("#status").textContent = res.error; $("#status").classList.add("err"); return; }
  rows = res.mappings;
  picker = res.picker;
  saved = snapshot();
  lastImport = "";
  notice = res.notice;
  render();
};
$("#pickerPill").onclick = e => { e.stopPropagation(); recording === null ? startRecording("picker") : stopRecording(null); };
$("#pickerOn").onchange = e => { picker.enabled = e.target.checked; validate(); };
$("#startup").onchange = async e => { e.target.checked = await api.set_startup(e.target.checked); };
$("#desktop").onchange = async e => { e.target.checked = await api.set_desktop(e.target.checked); };
$("#quit").onclick = () => api.quit();
function showActive() {
  document.body.classList.toggle("off", !active);
  $("#toggle").textContent = active ? "Deactivate" : "Activate";
  $("#toggle").classList.toggle("go", !active);
  $("#toggle").title = active ? "Turn all shortcuts off without closing Kemper" : "Turn shortcuts back on";
}
$("#toggle").onclick = async () => {
  const s = await api.set_active(!active);
  active = s.active;
  notice = s.notice;
  showActive();
  validate();
};

function applyTheme(save) {
  const dark = appearance === "dark" || (appearance === "system" && media.matches);
  document.documentElement.classList.toggle("dark", dark);
  document.querySelectorAll("#appearance button").forEach(b => b.classList.toggle("on", b.dataset.v === appearance));
  api?.set_appearance(save ? appearance : "", dark);
}
$("#appearance").onclick = e => { const v = e.target.dataset?.v; if (v) { appearance = v; applyTheme(true); } };
media.addEventListener("change", () => applyTheme(false));

// Called on start, and by Kemper when the settings change from the command line.
async function refresh() {
  recording = null;
  const s = await api.state();
  rows = s.mappings;
  picker = s.picker;
  saved = snapshot();
  notice = s.notice;
  appearance = s.appearance;
  $("#startup").checked = s.startup;
  $("#desktop").checked = s.desktop;
  MODN = s.mod_names || {};
  $("#desktopRow").hidden = !s.can_desktop;
  $("#startupLabel").textContent = s.os === "Windows" ? "Start with Windows" : "Start at login";
  if (s.os !== "Windows") $("#pickerFoot").textContent = "Press it in any app to see all your shortcuts and pick one to type.";
  if (!s.can_keypack_files) $("#kpFoot").textContent = "Keypacks are sets of shortcuts in .kmppck files that you can share. Open one with Import a keypack.";
  active = s.active;
  showActive();
  applyTheme(false);
  lastImport = "";
  render();
  openPendingKeypack();
}

// ---------- keypacks ----------
let lastImport = "";
function choice(title, sub, onclick) {
  const b = el("button", "choice");
  b.append(el("b", "", title), el("small", "", sub));
  b.onclick = onclick;
  return b;
}
$("#kpCreate").onclick = () => openSheet("Create a keypack", "A keypack is a set of shortcuts in one .kmppck file that you can share.", [
  choice("New keypack", "Start from scratch in the Keypack Editor.", () => { closeSheet(); api.open_editor(null); }),
  choice("Make one with AI…", "Describe what you want to an AI chat, then paste its answer into the Keypack Editor.", () => { closeSheet(); api.open_editor(null, true); }),
  choice("Edit a keypack file…", "Open a .kmppck file in the Keypack Editor and change it.", async () => {
    const p = await api.choose_keypack();
    if (p) { closeSheet(); api.open_editor(p); }
  }),
], [button("Cancel", "", closeSheet)]);
$("#kpImport").onclick = async () => { const p = await api.choose_keypack(); if (p) openKeypack(p); };
$("#kpMarket").onclick = () => api.open_marketplace();

// The import question: what's in the keypack, and what it would clash with. Conflicts don't block importing,
// they only block saving, the same as conflicts you make yourself.
async function openKeypack(path) {
  const r = await api.read_keypack(path);
  if (!r.ok) return openSheet("Can't open this keypack", r.file, el("p", "", r.error), [button("OK", "primary", closeSheet)]);
  const count = level => r.items.filter(i => i.level === level).length;
  const bad = count("bad"), warn = count("warn"), fresh = r.items.length - count("same");
  const list = el("div", "plist");
  r.items.forEach(it => {
    const row = el("div", "prow" + (it.level === "bad" ? " bad" : ""));
    row.append(el("div", "pill" + (it.level === "bad" ? " bad" : ""), it.label), el("div", "ptext", it.text.replace(/\r?\n/g, " ⏎ ")));
    if (it.issue) row.append(el("div", "issue " + it.level, it.issue));
    list.append(row);
  });
  let note, cls = "note";
  if (!r.items.length) note = "This keypack is empty.";
  else if (!fresh) note = "Everything in this keypack is already in your Kemper.";
  else if (bad) { note = `${bad} conflict${bad > 1 ? "s" : ""}. You can import, but Kemper won't save until you change the red ones.`; cls += " err"; }
  else if (warn) { note = "No conflicts, but the orange ones take over keys you may use a lot."; cls += " warn"; }
  else note = "No conflicts.";
  const go = button(fresh ? `Import ${fresh}` : "Import", "primary", () => {
    r.items.filter(i => i.level !== "same").forEach(i => rows.push({ mods: i.mods, vk: i.vk, key: i.key, text: i.text }));
    lastImport = `Imported ${fresh} shortcut${fresh > 1 ? "s" : ""} from “${r.name}”. Save to keep them.`;
    closeSheet();
    render();
    $("main").scrollTo({ top: 1e6, behavior: "smooth" });
  });
  go.disabled = !fresh;
  openSheet(`Import “${r.name}”?`, `${r.file} · ${r.items.length} shortcut${r.items.length === 1 ? "" : "s"}`,
            list, [el("div", cls, note), button("Cancel", "", closeSheet), go], true);
}
async function openPendingKeypack() {
  const p = await api.take_pending_keypack();
  if (p) openKeypack(p);
}
window.addEventListener("pywebviewready", () => { api = window.pywebview.api; refresh(); });
</script>
</body>
</html>
'''

# ---------- the quick picker popup's page ----------
PICKER_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Kemper Picker</title>
<style>
  :root { --bg: #FFFFFF; --text: #1C1C1E; --sub: #8E8E93; --sep: rgba(60,60,67,.14); --field: rgba(118,118,128,.12);
          --hover: rgba(118,118,128,.10); --sel: rgba(0,122,255,.14); --blue: #007AFF; --pill: #EEEEF3; color-scheme: light; }
  :root.dark { --bg: #1C1C1E; --text: #FFFFFF; --sub: #8E8E93; --sep: rgba(84,84,88,.5); --field: rgba(118,118,128,.24);
               --hover: rgba(255,255,255,.06); --sel: rgba(10,132,255,.28); --blue: #0A84FF; --pill: #2C2C2E; color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; }
  body { background: var(--bg); color: var(--text); font: 14px/1.3 "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
         display: flex; flex-direction: column; overflow: hidden; user-select: none; -webkit-user-select: none; }
  header { padding: 0 14px 10px; border-bottom: 1px solid var(--sep); }
  .grab { cursor: move; padding-top: 7px; }
  .handle { width: 36px; height: 5px; border-radius: 3px; background: var(--sep); margin: 0 auto 8px; }
  .grab:hover .handle { background: var(--sub); }
  .top { display: flex; justify-content: space-between; align-items: baseline; margin: 0 2px; padding-bottom: 9px; }
  .title { font-weight: 600; font-size: 15px; }
  .keys { color: var(--sub); font-size: 12px; }
  #q { width: 100%; border: 0; outline: 0; border-radius: 10px; background: var(--field); color: var(--text);
       font: inherit; font-size: 15px; padding: 9px 12px; user-select: text; -webkit-user-select: text; }
  #q::placeholder { color: var(--sub); }
  #list { flex: 1; overflow-y: auto; padding: 6px; }
  #list::-webkit-scrollbar { width: 8px; }
  #list::-webkit-scrollbar-thumb { background: var(--sep); border-radius: 8px; }
  .item { display: flex; align-items: center; gap: 12px; padding: 8px 10px; border-radius: 10px; cursor: pointer; min-height: 48px; }
  .item:hover { background: var(--hover); }
  .item.sel { background: var(--sel); }
  .glyph { flex: 1; min-width: 0; font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .glyph.big { font-size: 24px; line-height: 1.1; }
  .combo { flex: none; font-size: 12px; font-weight: 600; color: var(--sub); background: var(--pill); border-radius: 7px; padding: 4px 8px; }
  .item.sel .combo { color: var(--blue); }
  .empty { color: var(--sub); text-align: center; padding: 40px 24px; }
</style>
</head>
<body>
<header>
  <!-- drag the popup by this strip; the search box below must stay clickable, so it's outside the region -->
  <div class="grab pywebview-drag-region" title="Drag to move">
    <div class="handle"></div>
    <div class="top"><span class="title">Kemper</span><span class="keys">↑ ↓ to move · Enter to type · Esc to close</span></div>
  </div>
  <input id="q" placeholder="Search your shortcuts" spellcheck="false" aria-label="Search your shortcuts">
</header>
<div id="list" role="listbox" aria-label="Shortcuts"></div>
<script>
let api, items = [], shown = [], sel = 0, lastMouse = null;
const q = document.getElementById("q"), list = document.getElementById("list");

// Kemper calls this each time the picker combo is pressed, just before showing the popup.
async function openPicker() {
  if (!api) return;
  const s = await api.picker_items();
  document.documentElement.classList.toggle("dark", s.dark);
  items = s.items;
  q.value = "";
  sel = 0;
  lastMouse = null;
  draw();
  setTimeout(() => q.focus(), 30);
}
function draw() {
  const t = q.value.trim().toLowerCase();
  shown = items.filter(it => !t || it.text.toLowerCase().includes(t) || it.label.toLowerCase().includes(t));
  list.replaceChildren();
  if (!shown.length) {
    const e = document.createElement("div");
    e.className = "empty";
    e.textContent = items.length ? "No shortcut matches." : "No shortcuts yet. Add some in Kemper's window.";
    list.append(e);
    return;
  }
  shown.forEach((it, n) => {
    const row = document.createElement("div");
    row.className = "item";
    row.setAttribute("role", "option");
    const g = document.createElement("div");
    g.className = "glyph" + ([...it.text].length <= 3 ? " big" : "");
    g.textContent = it.text.replace(/\r?\n/g, " ⏎ ");
    g.title = it.text;
    const c = document.createElement("div");
    c.className = "combo";
    c.textContent = it.label;
    row.append(g, c);
    row.onclick = () => api.pick(it.i);
    row.onmousemove = e => {
      // The popup opens under the pointer, which fires mousemove without the mouse moving; only real moves select.
      const pos = e.screenX + "," + e.screenY;
      if (lastMouse === null || lastMouse === pos) { lastMouse = pos; return; }
      lastMouse = pos;
      if (sel !== n) { sel = n; mark(); }
    };
    list.append(row);
  });
  mark();
}
function mark() {
  [...list.children].forEach((el, n) => {
    el.classList.toggle("sel", n === sel);
    el.setAttribute("aria-selected", n === sel);
  });
  list.children[sel]?.scrollIntoView({ block: "nearest" });
}
q.oninput = () => { sel = 0; draw(); };
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { e.preventDefault(); api?.close_picker(true); }
  else if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(sel + 1, shown.length - 1); mark(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(sel - 1, 0); mark(); }
  else if (e.key === "Enter" && shown[sel]) { e.preventDefault(); api.pick(shown[sel].i); }
});
window.addEventListener("blur", () => api?.close_picker(false)); // clicked elsewhere
window.addEventListener("focus", () => q.focus());
window.addEventListener("pywebviewready", () => { api = window.pywebview.api; });
</script>
</body>
</html>
'''

# ---------- instructions that teach an AI chat to write keypacks (also in docs/AI_INSTRUCTIONS.md) ----------
AI_INSTRUCTIONS = r'''# Instructions: create a Kemper keypack

You are helping someone make a keypack for Kemper, an app for Windows, macOS and Linux that types a character or some text whenever a key combination is pressed (for example, Alt+2 types ²). A keypack is a JSON file with the extension .kmppck that holds a named set of these shortcuts. After these instructions, the person will tell you what they want; build the keypack from that.

## Your reply

1. Put the complete keypack in a single ```json code block. Inside the block, write only the JSON, with no comments.
2. Below the block, add a short table of the combos and what each one types, so the person knows which keys to press.
3. If the request is too vague to choose good shortcuts, ask one short question first. Otherwise, make sensible choices yourself.

## The format

```json
{
  "format": "kemper-keypack",
  "version": 1,
  "name": "Short descriptive name",
  "mappings": [
    { "keys": "Alt+2", "text": "²" }
  ]
}
```

- "format" must be exactly "kemper-keypack", and "version" must be 1.
- "name" is what people see when they import the keypack: 1 to 100 characters.
- "mappings" is the list of shortcuts, from 1 to 1000 of them. Each one has exactly two fields, "keys" and "text".

## "keys": the key combination

- Write it as modifiers plus one key, joined with +, for example "Ctrl+Alt+E" or "Alt+Shift+2".
- Modifiers: Ctrl, Alt, Shift, Win.
- Keys:
  - letters A-Z and digits 0-9
  - F1-F24
  - Num0-Num9 (number pad)
  - Space, Enter, Tab, Esc, Backspace, Delete, Insert, Home, End, PageUp, PageDown, Left, Right, Up, Down
  - the punctuation keys - = [ ] ; ' , . / ` \
- Name the physical key on a US keyboard. A character that needs Shift is written as Shift plus its key: "Shift+1", never "!".
- Every mapping must use a different combination. Modifier order doesn't matter: "Alt+Shift+2" and "Shift+Alt+2" are the same combination.
- Always include Ctrl or Alt. Shift alone, or no modifier at all, would replace normal typing.
- Don't use combinations that Windows or most apps already need:
  - Ctrl+A, C, F, N, O, P, S, T, V, W, X, Y and Z
  - Alt+Tab, Alt+F4 and Ctrl+Alt+Delete
  - Win+anything
- Prefer Ctrl+Alt+key, Alt+key and Alt+Shift+key.
- Make combos easy to remember:
  - use the first letter, or a key the output looks like (Ctrl+Alt+E for €, Alt+A for α)
  - use Shift for a variant (Alt+2 → ², Alt+Shift+2 → ₂)
  - use arrow keys for arrows

## "text": what gets typed

- Any Unicode text from 1 to 10,000 characters: a symbol, an emoji, a word or whole sentences.
- Write a line break as \n (Kemper presses Enter there). Escape " and \ the way JSON requires.

## What the person does with your reply

They copy your reply into Kemper (Keypack Editor → AI → paste), or save the JSON as a file ending in .kmppck and double-click it. Kemper then shows every shortcut and any conflicts before importing.

## Example

Request: "Greek letters for my math notes: alpha, beta, pi and sigma, plus capital sigma."

```json
{
  "format": "kemper-keypack",
  "version": 1,
  "name": "Greek letters for math",
  "mappings": [
    { "keys": "Alt+A", "text": "α" },
    { "keys": "Alt+B", "text": "β" },
    { "keys": "Alt+P", "text": "π" },
    { "keys": "Alt+S", "text": "σ" },
    { "keys": "Alt+Shift+S", "text": "Σ" }
  ]
}
```

| Press | Types |
|---|---|
| Alt+A | α |
| Alt+B | β |
| Alt+P | π |
| Alt+S | σ |
| Alt+Shift+S | Σ |'''

# ---------- JS shared by the window and the Keypack Editor: DOM helpers and iOS-style sheets ----------
SHARED_JS = r'''
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
function button(text, cls, onclick) {
  const b = el("button", "btn" + (cls ? " " + cls : ""), text);
  b.onclick = onclick;
  return b;
}
let sheetOpen = false;
function openSheet(title, sub, body, foot, wide) {
  const s = document.getElementById("sheet"), o = document.getElementById("overlay");
  s.replaceChildren();
  s.classList.toggle("wide", !!wide);
  const head = el("div", "shead");
  head.append(el("h2", "", title));
  if (sub) head.append(el("div", "sub", sub));
  const b = el("div", "sbody");
  if (body) b.append(...[].concat(body));
  const f = el("div", "sfoot");
  f.append(...foot);
  s.append(head, b, f);
  o.hidden = false;
  sheetOpen = true;
  requestAnimationFrame(() => o.classList.add("show"));
  (f.querySelector(".primary:not(:disabled)") || f.querySelector("button"))?.focus();
}
function closeSheet() {
  const o = document.getElementById("overlay");
  o.classList.remove("show");
  sheetOpen = false;
  setTimeout(() => { if (!sheetOpen) o.hidden = true; }, 220);
}
document.getElementById("overlay").addEventListener("mousedown", e => { if (e.target.id === "overlay") closeSheet(); });
'''

# ---------- the Keypack Editor's page (styles come from the main window's page) ----------
EDITOR_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Kemper Keypack Editor</title>
<style>
/*KEMPER_CSS*/
  :root { --sel-bg: rgba(0,122,255,.07); }
  :root.dark { --sel-bg: rgba(10,132,255,.16); }
  .toolbar { flex: none; display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: var(--bar);
    border-bottom: 1px solid var(--sep); backdrop-filter: saturate(180%) blur(20px); }
  .mid { flex: 1; display: flex; justify-content: center; align-items: center; gap: 6px; }
  .tool { border: 0; background: var(--seg); color: var(--text); border-radius: 9px; padding: 8px 13px; font-size: 13.5px; font-weight: 600;
    cursor: pointer; display: inline-flex; align-items: center; gap: 6px; transition: background-color .15s ease, opacity .15s ease; }
  .tool:hover:not(:disabled) { background: var(--sep); }
  .tool:disabled { opacity: .35; cursor: default; }
  .tool.primary { background: var(--blue); color: #fff; }
  .tool.primary:hover:not(:disabled) { background: var(--blue); filter: brightness(1.08); }
  .tool .ic { font-size: 15px; line-height: 1; }
  .tsep { width: 1px; height: 22px; background: var(--sep); margin: 0 4px; }
  .packhead { margin: 2px 4px 16px; }
  .packname { font: 700 26px/1.15 "Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif; letter-spacing: -.3px; overflow-wrap: anywhere; }
  .packfile { color: var(--sub); font-size: 12.5px; margin-top: 4px; }
  #canvas .row { cursor: default; }
  #canvas .row.sel { background: var(--sel-bg); box-shadow: inset 3px 0 0 var(--blue); }
  #canvas .row.bad.sel { background: var(--red-bg); }
  .empty { text-align: center; color: var(--sub); padding: 70px 30px; border: 2px dashed var(--sep); border-radius: 14px; }
  .empty b { display: block; color: var(--text); font-size: 17px; margin-bottom: 6px; }
  .gtools { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-size: 13px; color: var(--sub); }
  .link2 { border: 0; background: none; color: var(--blue); font-size: 13px; font-weight: 600; cursor: pointer; padding: 4px 8px; border-radius: 6px; }
  .link2:hover { background: var(--seg); }
  .gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; padding-bottom: 4px; }
  .tile { position: relative; border: 2px solid transparent; background: var(--bg); border-radius: 12px; padding: 16px 8px 10px; cursor: pointer;
    color: var(--text); text-align: center; min-width: 0; transition: border-color .12s ease, background-color .12s ease; }
  .tile:hover:not(:disabled) { border-color: var(--sep); }
  .tile.on { border-color: var(--blue); background: var(--sel-bg); }
  .tile .g { font-size: 26px; height: 34px; line-height: 34px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tile .g.long { font-size: 14px; }
  .tile .c { font-size: 11px; font-weight: 600; color: var(--sub); margin-top: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tile .chk { position: absolute; top: 6px; right: 6px; width: 20px; height: 20px; border-radius: 50%; border: 2px solid var(--sep); background: var(--card); }
  .tile.on .chk { background: var(--blue); border-color: var(--blue); }
  .tile.on .chk::after { content: ""; position: absolute; left: 5px; top: 1px; width: 5px; height: 10px; border: solid #fff; border-width: 0 2px 2px 0; transform: rotate(45deg); }
  .tile:disabled { opacity: .45; cursor: default; }
</style>
</head>
<body>
<div class="toolbar">
  <button class="tool" id="importBtn" title="Add shortcuts from your Kemper"><span class="ic">⤓</span>Import</button>
  <button class="tool" id="aiBtn" title="Make shortcuts with an AI chat"><span class="ic">✦</span>AI</button>
  <div class="mid">
    <button class="tool" id="addBtn" title="Add a shortcut (Ctrl+N)"><span class="ic">＋</span>Add</button>
    <button class="tool" id="removeBtn" title="Remove the selected shortcut (Delete)"><span class="ic">－</span>Remove</button>
    <span class="tsep"></span>
    <button class="tool" id="undoBtn" title="Undo (Ctrl+Z)"><span class="ic">↶</span>Undo</button>
    <button class="tool" id="redoBtn" title="Redo (Ctrl+Y)"><span class="ic">↷</span>Redo</button>
  </div>
  <button class="tool primary" id="exportBtn" title="Save as a .kmppck file (Ctrl+S)">Export</button>
</div>
<main>
  <div class="packhead"><div class="packname" id="packName"></div><div class="packfile" id="packFile"></div></div>
  <div id="canvas"></div>
</main>
<footer><div id="status"></div></footer>
<div class="overlay" id="overlay" hidden><div class="sheet" id="sheet" role="dialog" aria-modal="true"></div></div>
<script>
/*SHARED_JS*/
let api, rows = [], name = "", file = "", folder = "", sel = -1, recording = null, saved = "", dirtySent = false;
let undo = [], redo = [], lastKey = "", lastTime = 0;
const $ = s => document.querySelector(s);
const ORDER = ["Ctrl", "Alt", "Shift", "Win"];
const MOD_KEYS = ["Control", "Alt", "Shift", "Meta", "AltGraph", "OS"];
const HISTORY = 50;
const id = r => [...r.mods].sort().join("+") + "|" + r.vk;
let MODN = {};  // Kemper's modifier names in this system's words: Cmd and Option on a Mac, Super on Linux
const label = r => [...r.mods].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b)).map(m => MODN[m] || m).concat(r.key).join(" + ");
const snap = () => JSON.stringify({ name, rows });
const plain = m => ({ mods: m.mods, vk: m.vk, key: m.key, text: m.text });

// ---------- undo / redo: each change first stores the state before it (last 50 kept) ----------
// Typing in one text field counts as one step until you pause for 1.5 s or move elsewhere.
function remember(key) {
  const now = Date.now();
  if (key && key === lastKey && now - lastTime < 1500) { lastTime = now; return; }
  lastKey = key || "";
  lastTime = now;
  undo.push(snap());
  if (undo.length > HISTORY) undo.shift();
  redo = [];
}
function restore(state) {
  const o = JSON.parse(state);
  name = o.name;
  rows = o.rows;
  sel = Math.min(sel, rows.length - 1);
  lastKey = "";
}
function doUndo() {
  if (!undo.length || recording !== null) return;
  redo.push(snap());
  restore(undo.pop());
  render();
}
function doRedo() {
  if (!redo.length || recording !== null) return;
  undo.push(snap());
  restore(redo.pop());
  render();
}

// ---------- the canvas ----------
function conflicts() {
  const n = {};
  rows.filter(r => r.vk).forEach(r => n[id(r)] = (n[id(r)] || 0) + 1);
  return new Set(Object.keys(n).filter(k => n[k] > 1));
}
function render() {
  $("#packName").textContent = name || "New keypack";
  $("#packFile").textContent = file || "Not exported yet";
  const c = $("#canvas");
  c.replaceChildren();
  if (!rows.length) {
    const e = el("div", "empty");
    e.append(el("b", "", "This keypack is empty"), el("span", "", "Click Add to make a shortcut, or Import to bring in shortcuts from your Kemper."));
    c.append(e);
  } else {
    const card = el("div", "card");
    rows.forEach((r, i) => {
      const row = el("div", "row");
      row.onmousedown = () => select(i);
      const pill = el("button", "pill");
      pill.onclick = e => { e.stopPropagation(); select(i); recording === null ? startRecording(i) : stopRecording(null); };
      const text = el("input", "text");
      text.placeholder = "Text to type";
      text.value = r.text;
      text.spellcheck = false;
      text.onfocus = () => select(i);
      text.oninput = () => { remember("text" + i); r.text = text.value; changed(); };
      row.append(pill, text);
      card.append(row);
    });
    c.append(card);
  }
  changed();
}
function select(i) {
  sel = i;
  [...document.querySelectorAll("#canvas .row")].forEach((r, n) => r.classList.toggle("sel", n === sel));
  $("#removeBtn").disabled = sel < 0 || recording !== null;
}
function changed() {
  const dup = conflicts();
  [...document.querySelectorAll("#canvas .row")].forEach((row, i) => {
    const r = rows[i], pill = row.querySelector(".pill"), bad = !!r.vk && dup.has(id(r));
    row.classList.toggle("bad", bad);
    row.classList.toggle("sel", i === sel);
    pill.className = "pill" + (recording === i ? " recording" : bad ? " bad" : r.vk ? "" : " empty");
    pill.textContent = recording === i ? "Press keys…" : r.vk ? label(r) : "Set keys";
    pill.title = recording === i ? "Press a key combo · Esc to cancel" : "Click to change";
  });
  const busy = recording !== null, incomplete = rows.some(r => !r.vk || !r.text), dirty = snap() !== saved;
  let msg, err = false;
  if (busy) msg = "Press the combo now. Esc cancels.";
  else if (!rows.length) msg = "Add shortcuts, then export the keypack to share it.";
  else if (dup.size) { msg = "Two shortcuts use the same keys. Change the red ones before exporting."; err = true; }
  else if (incomplete) msg = "Every shortcut needs both keys and text.";
  else msg = `${rows.length} shortcut${rows.length === 1 ? "" : "s"}` + (dirty ? " · not exported yet" : " · exported");
  $("#status").textContent = msg;
  $("#status").classList.toggle("err", err);
  $("#undoBtn").disabled = !undo.length || busy;
  $("#redoBtn").disabled = !redo.length || busy;
  $("#removeBtn").disabled = sel < 0 || busy;
  $("#addBtn").disabled = $("#importBtn").disabled = $("#aiBtn").disabled = busy;
  $("#exportBtn").disabled = busy || !rows.length || !!dup.size || incomplete;
  if (dirty !== dirtySent && api) { dirtySent = dirty; api.set_editor_dirty(dirty); }
}
function addRow() {
  if (recording !== null) return;
  remember();
  rows.push({ mods: [], vk: 0, key: "", text: "" });
  sel = rows.length - 1;
  render();
  startRecording(sel);
  $("main").scrollTo({ top: 1e6, behavior: "smooth" });
}
function removeRow() {
  if (sel < 0 || recording !== null) return;
  remember();
  rows.splice(sel, 1);
  sel = Math.min(sel, rows.length - 1);
  render();
}

// ---------- recording combos, as in Kemper's window ----------
async function startRecording(i) {
  if (recording !== null) return;
  document.activeElement?.blur();
  recording = i;
  changed();
  await api.capture(true);
}
async function stopRecording(update) {
  const i = recording;
  recording = null;
  if (update) { remember(); Object.assign(rows[i], update); }
  await api.capture(false);
  changed();
}
document.addEventListener("keydown", async e => {
  if (sheetOpen) {
    if (e.key === "Escape") { e.preventDefault(); closeSheet(); }
    return;
  }
  if (recording !== null) {
    e.preventDefault();
    e.stopPropagation();
    if (MOD_KEYS.includes(e.key)) return;
    const mods = [];
    if (e.ctrlKey) mods.push("Ctrl");
    if (e.altKey) mods.push("Alt");
    if (e.shiftKey) mods.push("Shift");
    if (e.metaKey) mods.push("Win");
    if (e.key === "Escape" && !mods.length) return stopRecording(null);
    const vk = e.keyCode, i = recording;
    await stopRecording({ mods, vk, key: await api.key_name(vk) });
    const input = document.querySelectorAll("#canvas .text")[i];
    if (input && !input.value) input.focus();
    return;
  }
  const k = e.key.toLowerCase(), typing = document.activeElement?.tagName === "INPUT";
  if (e.ctrlKey && k === "z" && !e.shiftKey) { e.preventDefault(); doUndo(); }
  else if (e.ctrlKey && (k === "y" || (k === "z" && e.shiftKey))) { e.preventDefault(); doRedo(); }
  else if (e.ctrlKey && k === "s") { e.preventDefault(); exportSheet(); }
  else if (e.ctrlKey && k === "n") { e.preventDefault(); addRow(); }
  else if (e.key === "Delete" && !typing) { e.preventDefault(); removeRow(); }
}, true);
document.addEventListener("click", () => { if (recording !== null) stopRecording(null); });
window.addEventListener("blur", () => { if (recording !== null) stopRecording(null); });

// ---------- import from Kemper: a gallery to pick from ----------
async function importSheet() {
  const mine = await api.my_mappings();
  if (!mine.length) return openSheet("Import from Kemper", "", el("p", "", "You don't have any shortcuts in Kemper yet."), [button("OK", "primary", closeSheet)]);
  const have = new Set(rows.map(r => id(r) + "\u0000" + r.text));
  const selectable = mine.map((m, i) => i).filter(i => !have.has(id(mine[i]) + "\u0000" + mine[i].text));
  const chosen = new Set();
  const grid = el("div", "gallery"), count = el("span"), all = el("button", "link2");
  const add = button("Add", "primary", () => {
    remember();
    mine.filter((m, i) => chosen.has(i)).forEach(m => rows.push(plain(m)));
    sel = rows.length - 1;
    closeSheet();
    render();
    $("main").scrollTo({ top: 1e6, behavior: "smooth" });
  });
  function update() {
    [...grid.children].forEach((t, i) => t.classList.toggle("on", chosen.has(i)));
    count.textContent = `${chosen.size} of ${selectable.length} selected`;
    all.textContent = selectable.length && chosen.size === selectable.length ? "Deselect all" : "Select all";
    all.disabled = !selectable.length;
    add.textContent = chosen.size ? `Add ${chosen.size}` : "Add";
    add.disabled = !chosen.size;
  }
  all.onclick = () => {
    if (chosen.size === selectable.length) chosen.clear();
    else selectable.forEach(i => chosen.add(i));
    update();
  };
  mine.forEach((m, i) => {
    const t = el("button", "tile"), inPack = !selectable.includes(i);
    t.disabled = inPack;
    t.title = inPack ? "Already in this keypack" : m.text;
    t.append(el("span", "chk"), el("div", "g" + ([...m.text].length > 3 ? " long" : ""), m.text.replace(/\r?\n/g, " ⏎ ")),
             el("div", "c", inPack ? "In keypack" : m.label));
    t.onclick = () => { chosen.has(i) ? chosen.delete(i) : chosen.add(i); update(); };
    grid.append(t);
  });
  const tools = el("div", "gtools");
  tools.append(count, all);
  openSheet("Import from Kemper", "Pick the shortcuts to add to this keypack.", [tools, grid], [button("Cancel", "", closeSheet), add], true);
  update();
}

// ---------- AI: copy the instructions, describe what you want to any AI chat, paste its answer ----------
async function aiSheet() {
  if (sheetOpen || recording !== null) return;
  const instructions = await api.ai_instructions();
  const step = (n, title, sub, ...extra) => {
    const s = el("div", "step"), b = el("div", "body");
    b.append(el("b", "", title), el("small", "", sub), ...extra);
    s.append(el("div", "n", n), b);
    return s;
  };
  const view = el("textarea", "area");
  view.readOnly = true;
  view.value = instructions;
  view.hidden = true;
  const copy = button("Copy instructions", "primary", async () => {
    const ok = (await api.copy_text(instructions)) || await navigator.clipboard?.writeText(instructions).then(() => true, () => false);
    copy.textContent = ok ? "Copied ✓" : "Couldn't copy. Use Show and copy it from there";
    setTimeout(() => { copy.textContent = "Copy instructions"; }, 2000);
  });
  const show = button("Show", "", () => { view.hidden = !view.hidden; show.textContent = view.hidden ? "Show" : "Hide"; });
  const btns = el("div", "btns");
  btns.append(copy, show);
  const answer = el("textarea", "area");
  answer.placeholder = "Paste the AI's whole answer here. Kemper finds the keypack in it.";
  answer.spellcheck = false;
  const note = el("div", "note");
  const add = button("Add to keypack", "primary", async () => {
    const r = await api.parse_keypack_text(answer.value);
    if (!r.ok) { note.textContent = r.error; note.className = "note err"; return; }
    remember();
    r.items.forEach(m => rows.push(plain(m)));
    if (!name) name = r.name;
    sel = rows.length - 1;
    closeSheet();
    render();
    $("main").scrollTo({ top: 1e6, behavior: "smooth" });
  });
  answer.oninput = () => { add.disabled = !answer.value.trim(); note.textContent = ""; note.className = "note"; };
  add.disabled = true;
  openSheet("Make a keypack with AI", "Works with ChatGPT, Claude, Gemini, Copilot or any other AI chat.", [
    step("1", "Copy the instructions into a new AI chat", "They teach the AI how Kemper keypacks work.", btns, view),
    step("2", "Tell it what you want", "For example: “Greek letters for math, and arrows on Ctrl+Alt with the arrow keys.”"),
    step("3", "Paste its answer here", "The shortcuts are added to this keypack, where you can check and change them before exporting.", answer),
  ], [note, button("Cancel", "", closeSheet), add], true);
  copy.focus();
}

// ---------- export ----------
const safeName = s => s.trim().replace(/[<>:"/\\|?*\x00-\x1f]/g, "").replace(/\s+/g, " ").replace(/[. ]+$/, "");
function field(title, control, hint) {
  const f = el("div", "field");
  f.append(el("span", "", title), control);
  if (hint) f.append(el("small", "", hint));
  return f;
}
async function exportSheet() {
  if ($("#exportBtn").disabled || sheetOpen) return;
  if (!folder) folder = await api.default_folder();
  const nameIn = el("input", "input"), fileIn = el("input", "input");
  nameIn.value = name;
  nameIn.placeholder = "Math symbols";
  nameIn.maxLength = 100;
  fileIn.value = file ? file.replace(/\.kmppck$/i, "") : safeName(name);
  fileIn.placeholder = "Math symbols";
  let fileEdited = !!file, replace = false;
  const where = el("div", "path", folder);
  const note = el("div", "note");
  const go = button("Export", "primary", async () => {
    const res = await api.export_keypack(nameIn.value, fileIn.value, folder, rows.map(plain), replace);
    if (res.exists) {
      replace = true;
      go.textContent = "Replace";
      go.className = "btn danger";
      note.textContent = `${res.file} is already in this folder. Click Replace to overwrite it.`;
      note.className = "note err";
      return;
    }
    if (!res.ok) { note.textContent = res.error; note.className = "note err"; return; }
    name = res.name;
    file = res.file;
    folder = res.folder;
    saved = snap();
    render();
    openSheet("Keypack exported", res.path, el("p", "", `“${name}” is ready to share. Double-clicking the file opens Kemper and asks whether to import it.`),
              [button("Show in folder", "", () => api.show_in_folder(res.path)), button("Done", "primary", closeSheet)]);
  });
  const reset = () => { replace = false; go.textContent = "Export"; go.className = "btn primary"; note.textContent = ""; note.className = "note"; };
  nameIn.oninput = () => { if (!fileEdited) fileIn.value = safeName(nameIn.value); reset(); };
  fileIn.oninput = () => { fileEdited = true; reset(); };
  const choose = button("Choose…", "", async () => {
    const f = await api.choose_folder(folder);
    if (f) { folder = f; where.textContent = f; reset(); }
  });
  const sfx = el("div", "suffix"), fold = el("div", "folder");
  sfx.append(fileIn, el("em", "", ".kmppck"));
  fold.append(where, choose);
  openSheet("Export keypack", `${rows.length} shortcut${rows.length === 1 ? "" : "s"}`, [
    field("Keypack name", nameIn, "Shown when someone imports it. It can differ from the file name."),
    field("File name", sfx),
    field("Folder", fold),
  ], [note, button("Cancel", "", closeSheet), go]);
  nameIn.focus();
}

// ---------- opening, closing ----------
async function load(path) {
  name = ""; file = ""; rows = []; sel = -1; undo = []; redo = []; lastKey = "";
  if (path) {
    const r = await api.read_keypack(path);
    if (r.ok) {
      name = r.name;
      file = r.file;
      folder = r.folder;
      rows = r.items.map(plain);
    } else {
      openSheet("Can't open this keypack", r.file, el("p", "", r.error), [button("OK", "primary", closeSheet)]);
    }
  }
  saved = snap();
  render();
}
// Kemper calls this when you pick New or Edit while the editor is already open.
function requestLoad(path) {
  if (snap() === saved) return load(path);
  openSheet("Discard your changes?", "This keypack has changes you haven't exported.", null,
            [button("Keep editing", "", closeSheet), button("Discard", "danger", () => { closeSheet(); load(path); })]);
}
// Kemper calls this when you close the window with changes you haven't exported.
function askClose() {
  openSheet("Close without exporting?", "Your changes to this keypack will be lost.", null,
            [button("Keep editing", "", closeSheet), button("Discard", "danger", () => api.close_editor())]);
}
function setDark(d) { document.documentElement.classList.toggle("dark", d); }

$("#importBtn").onclick = e => { e.stopPropagation(); importSheet(); };
$("#aiBtn").onclick = e => { e.stopPropagation(); aiSheet(); };
$("#addBtn").onclick = e => { e.stopPropagation(); addRow(); };
$("#removeBtn").onclick = removeRow;
$("#undoBtn").onclick = doUndo;
$("#redoBtn").onclick = doRedo;
$("#exportBtn").onclick = exportSheet;
window.addEventListener("pywebviewready", async () => {
  api = window.pywebview.api;
  const b = await api.editor_boot();
  MODN = b.mod_names || {};
  setDark(b.dark);
  await load(b.path);
  if (b.ai) aiSheet();
});
</script>
</body>
</html>
'''

UI_HTML = UI_HTML.replace("/*SHARED_JS*/", SHARED_JS)
EDITOR_HTML = (EDITOR_HTML.replace("/*KEMPER_CSS*/", re.search(r"<style>(.*?)</style>", UI_HTML, re.S).group(1))
               .replace("/*SHARED_JS*/", SHARED_JS))

# ---------- Kemper's icon: PNGs by size, turned into an .ico by icon_path() ----------
ICON_PNGS = {
    16: "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAACk0lEQVR42n2TP0tjeRSGn9+9upPEQDAQtFORWIhoI4ooaSzERncYxiJVChcLsRXsBcEUAT+AEoJWolgEJFj4BawEnULUsZTcnSrcf7m/d4tx/rA7s297OAfOc84DgOd5a2EYforjOI6i2AZBIN/3FUWRoiiS7weKolhRFNs4juMwDD95nrcGQLv95UO32030Fmutfpefa91uN2m3v3wwQRA+v3v3x5C1NjHGcY2BVqvF8fEx7XabKIooFotUq1X6+voAsJbEcXDDMPrc47rOkCQAF8T6+l88PDywubnJ2NgYuVyO5+dnjDHc3t5SLBZJpVKuJFzXGXIkkITjOGxsbGCt5fr6mvHxcaampnh8fCSVSpHJZDg/P2d9fR342iMBQRBIkq6urjQ3NydJ2tvbU7lcVqvV0szMjObn51Wr1SRJpVJJzWZTkuT7gfB9X5JUqVTUaDRkrdXs7KyCIND+/r5qtZqSJNH09LQk6fT0VOVy+fsAx3VdAF5fX5mcnMQYQzqd5unpiUKhQG9vLy8vL6TTaQAmJibwvL8BcF2XHn7KG0y2t7epVCpks1mstTQaDXZ2dt4uYDHmR4+TJAkAhUKBu7s7AJaXl6nX6+RyObLZLIeHh6yuriKJ+/t7+vv7AUiS5AfEy8tLlUolhWGoTqcjSapWq9rd3X3b9yurxcVFXVxc/GDgOC7WWpaWlhgdHeXs7IxMJgPA8PAwIyMjAKRSKba2thgYGGBlZQVrLa7rYuI41jeQxhg6nQ4HBwcMDg6ysLAAwM3NDUdHR+Tzeer1Oj09PRhjSJKEf72ycY0xNJtNTk5O8DwPgHw+z8ePa7x//+c3kInjOG4YRp//I9P/5Vcy8Xudvyss3w8UBMEvdf4HOoAqX2Gt4kgAAAAASUVORK5CYII=",
    20: "iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAADg0lEQVR42pWVzyt0bRjHv/fwlp4eZBRCpoONaTAoa1uFUBTFSjayeUs29lZeCjMlSRTZko3UmCz8AzSN3xaPxTRHM8OZM+eeOff3XYw5Hs/j7em9Vue6z7m/57q7Pvf3AgAcHh5+SyRSS5Zl/ZBS2pYllWVJWpZkJpOhaZpMp01mMhkW1i1Lqvy31o9EIrV0eHj4DQAQCoW+G0b6lL+Ebdv8P2EY6dNQKPRdJBKppfLy0r8BZAEUkxQk4XK5AAB3d3d4fHwESWiaBk3TIISAUgoulwtCCALIAfgrmXz9B6aZiZO0SSqlFJVSJMm9vT12dnayoaGBra2tbGtro9vt5srKylcFKpK2aWbisCyZX1GKtm3Ttm2OjY2xvr6e6+vrjMVizvFfXl74/PxMpRTPzs5oGIazlyQtS9IRLGwaHx+n3+9nIpEgScZiMZLk09MTI5GIU1J/fz/7+vo+7XUECwsHBwesqqpiMpmkbdvs7u7mwsICo9Eo6+rqWFNTw7GxMVqWxVQqxbq6Om5vbzuijmCh5K6uLq6trZEkg8Egm5qaKKXk3NwcR0ZGqOs6NU3j6uoqSXJra4s+n4+2bVMpRcuSdJEKQgg8PDxA13UMDQ2BJC4uLjA8PIzi4mK8vr6irKwMbrcbk5OTCIfDIImBgQEYhoFoNPrReaUIALi/v0dZWRmqq6shhIDf78fp6SmEECgvL0dJSQkA4OTkBO3t7RBCoLKyEm63G7e3twAAksjD9p4IIVBUVAQAmJqaQjabxfDwMC4vL3Fzc4PR0VHouo6ZmRmQ+UKEEHh/BAC4XC4BAGhsbEQymUQ8HgdJlJaWIhwOw+PxIBKJ4Pr6GtXV1Tg/P0dFRQUAIJVKQdd1NDU1OuJOU5RS9Pv93NzcJElms1kHkfn5ec7Ozjq5lHnU9vf36fV6mcvlnKZ8wmZ3d5e1tbWMxWLM5XI0DINSSk5PT3NiYoJSSgdmKSU9Hg83NjZ+x+ZnOAcHB7m4uPjpXgUCAS4vLzt5JpNhT08Pe3t7vwb74zrmX769vfH4+JjBYJC6rjtC8XicOzs7bG5uZm9vL03TdBh0BH82h5//dnR0xJaWFmqaxo6ODnZ0dFDTNHq9XgYCgQ9XyIs55vCbfQEQBYQA4OrqCg8PD459+Xw+B7P3zn62r/8y2MIxvoqvzLdgsPjTCDDNDNPp/AgwzT+PgH8Bu3ZOjKqCS64AAAAASUVORK5CYII=",
    24: "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAEZUlEQVR42rVWTUhbWRg99/qS2DbRiIQUpYg6VAoiFrWCG9tKpF1MI1SX0rXUneBCUXDhLIQW3IjdZNFlEcGZ0uLC1oFuCqO4KK0Ui8aKP1ibF2OavJf73uki5jVpdJgu5tskIfd9X+455zsngmSJEML68GGjtaoqOOLxuDsBVAAQ+LUigJhhmH/v7h78ce3ab/+QLAEA7O4e9BqGecJzyrIsWpY6fbWoVPb9eWUY5snu7kEvAGBzc6fZMEzztJGybZskads2lVL8lbJtm5ZlqdMh5ubmTrPQ9eM/y8t9v9u2bUkpSwCAJABACIFUKoUXL15geXkZ0WgUAFBdXY2uri6Ew2FomgbLslBSUgIhsqjmesXjib/Et2+p4wsXSr0khRACJJ2DMzMzmJiYwMnJCRobG1FXVwchBD5+/IhEIoE3b94gEAgUk5HtwVQqfYJ02vj5ijQMg319fRRCcGRkhDs7O0VwpNNph5/5+XnG43Gnx48zBp0B+Zj39vbS7/dzZWXFOZz7TinFo6OjgkE1NTUMhUKOCHJDCgbkGjx58oQAuLa2RpJ89+4dr169ysXFRcZiMba3t9Pn8/HOnTuMRqMkyfX1dWqaxkePHhX0KrpBMplkIBDg2NiY8+uuX7/OGzduUNd1jo2N8fLly5ybm2NDQwNbW1sdqKamplhWVkZd14shyml6fn6eFy9e5P7+Pi3L4tu3b+lyufj+/XuS5P3799nT00OS3NjYoMvl4uvXr2lZFmOxGMvKyvj06dNTbhTTaYMyX5avXr1CU1MTgsEgpJQ4PDzEpUuXEAwGoZSCpmnIZDIwDANVVVWoqKjA/v4+pJTw+/1oa2vD0tJSgaJkTu8AEI1GUVtb6wxsbm5GMpnE8+fPoWkapJSQUsLj8eDly5f48uUL2traHGnW1dXh8+fPpzskAQDaGfoFAJimierqagwNDeHBgwc4Pj6GrutIpVKYnZ3F4OAgHj58iPr6epimCZfLhdweFVQ6bTisDwwMsKOjI89/spKbnJxkMBhkeXk5/X4/A4EAx8fHHU/KPR8Khdjf31/AQQHJz549o9fr5dHRkbN0PwzMYDgcZigUcpSTU59t20wkEvT7/YxEIsUkS5nF6+7du3C73ZidnS24rmmacLvd8Pl88Hq98Hg8ME0TAKCUghACkUgESimEw+EsuVlbQ9GiTU9PU0rJ1dVV2rZNwzCYyWRo2zbv3bvHrq4u2rbNTCZDM2vC3Nraotvt5uTk5L8vWg7z7u5uDgwMFGXC1NQUJyYmCqD79OkTr1y5wlu3bjmcnGkV+UallGIymeTe3h4jkUiB9+Tq69evfPz4MUtLS3n79m3G43GHj/xNLrLrfLmura3h5s2bIImWlhbU1tZCCIGtrS2srq4ik8lgeHgYo6OjkFI6z+Xb9ZmBkz9E13UsLCxgeXkZ29vbTuB0dnaip6cHlZWVRTuUHzjnRubP3n5eKaWYH7M/R+YvhL7lYJz7/F9CX/zff1u+A3X2mk5Cx0m4AAAAAElFTkSuQmCC",
    32: "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",
    40: "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",
    48: "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",
    64: "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",
    256: "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",
}

if __name__ == "__main__":
    main()
