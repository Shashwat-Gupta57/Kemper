"""Kemper (Key Mapper): press a key combo (e.g. Alt+2), get a character or text (e.g. ²) typed anywhere in Windows.

One file. Run it to open the window, or see every command with:  python kemper.pyw --help
https://github.com/Shashwat-Gupta57/Kemper  ·  MIT License
"""
import argparse, base64, ctypes, json, os, re, shutil, socket, struct, subprocess, sys, threading, time, winreg

from ctypes import wintypes

APP = "Kemper"
VERSION = "2.0.0"
CONFIG = os.path.join(os.environ.get("APPDATA", "."), APP, "mappings.json")
PICKER_TITLE = "Kemper Picker"
PICKER_ID = 0xB000  # hotkey id of the quick picker; shortcut ids are 1..n
DEFAULT_PICKER = {"enabled": True, "mods": ["Ctrl", "Alt"], "vk": 0x4B, "key": "K"}
PORT = 47321  # single-instance socket; a second launch just tells the first to show its window
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32")

# name, virtual key, RegisterHotKey flag
MODS = [("Ctrl", 0x11, 0x2), ("Alt", 0x12, 0x1), ("Shift", 0x10, 0x4), ("Win", 0x5B, 0x8)]
MOD_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}
MOD_NOREPEAT, WM_HOTKEY, WM_QUIT = 0x4000, 0x0312, 0x0012
KEYUP, UNICODE = 0x2, 0x4

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

def held_mods():
    return [n for n, vk, _ in MODS if down(vk) or (n == "Win" and down(0x5C))]

def utf16_units(text):
    b = text.encode("utf-16-le")
    return [int.from_bytes(b[i:i + 2], "little") for i in range(0, len(b), 2)]

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

# ---------- mappings ----------
def combo_id(m):
    return (frozenset(m["mods"]), m["vk"])

def combo_label(m):
    order = [n for n, _, _ in MODS]
    return " + ".join(sorted(m["mods"], key=order.index) + [m["key"]])

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

def clean_mappings(rows, picker=None):
    """Validate mappings coming from the UI or CLI; raises ValueError so a bad config is never saved."""
    names = {n for n, _, _ in MODS}
    out = []
    for r in rows:
        mods, vk, key, text = r.get("mods"), r.get("vk"), r.get("key"), r.get("text")
        if not (isinstance(mods, list) and set(mods) <= names and isinstance(vk, int) and 0 < vk < 255
                and isinstance(key, str) and key and isinstance(text, str) and text):
            raise ValueError("Every shortcut needs both keys and text.")
        out.append({"mods": sorted(set(mods), key=[n for n, _, _ in MODS].index), "vk": vk, "key": key, "text": text})
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

def hotkey_flags(m):
    return MOD_NOREPEAT | sum(f for n, _, f in MODS if n in m["mods"])

class Listener(threading.Thread):
    """Owns the global hotkeys. RegisterHotKey ties them to this thread's message queue."""
    def __init__(self, rows, on_fire=None, picker=None, on_picker=None):
        super().__init__(daemon=True)
        self.rows, self.on_fire, self.failed, self.ready = rows, on_fire, [], threading.Event()
        self.picker, self.on_picker = picker, on_picker

    def run(self):
        self.tid = kernel32.GetCurrentThreadId()
        for i, m in enumerate(self.rows):
            if not user32.RegisterHotKey(None, i + 1, hotkey_flags(m), m["vk"]):
                self.failed.append(combo_label(m))
        if self.picker and not user32.RegisterHotKey(None, PICKER_ID, hotkey_flags(self.picker), self.picker["vk"]):
            self.failed.append(combo_label(self.picker) + " (quick picker)")
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

# ---------- start with Windows ----------
def pythonw():
    return sys.executable.replace("python.exe", "pythonw.exe")

def startup_cmd():
    return f'"{pythonw()}" "{os.path.abspath(__file__)}" --hidden'

def startup_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, APP)[0]
    except OSError:
        return None

def startup_enabled():
    return startup_value() == startup_cmd()

def set_startup(on):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, startup_cmd())
        else:
            try:
                winreg.DeleteValue(k, APP)
            except FileNotFoundError:
                pass

# ---------- Kemper's icon and desktop shortcut ----------
def icon_path():
    """Write Kemper's icon (embedded at the end of this file) to a real .ico, since Windows only takes files."""
    path = os.path.join(os.path.dirname(CONFIG), "kemper.ico")
    pngs = [(size, base64.b64decode(data)) for size, data in sorted(ICON_PNGS.items())]
    offset = 6 + 16 * len(pngs)
    entries, blobs = b"", b""
    for size, png in pngs:  # an .ico may hold PNG images directly (Windows Vista and later)
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset + len(blobs))
        blobs += png
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "wb") as f:
            f.write(struct.pack("<HHH", 0, 1, len(pngs)) + entries + blobs)
        os.replace(path + ".tmp", path)
    except OSError:
        pass  # an older copy may be in use; it's the same icon
    return path

def desktop_lnk():
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)  # CSIDL_DESKTOPDIRECTORY, follows OneDrive moves
    return os.path.join(buf.value, f"{APP}.lnk")

def desktop_enabled():
    return os.path.exists(desktop_lnk())

def set_desktop(on):
    """A .pyw file always shows Python's icon, so Kemper's own icon lives on a shortcut to it."""
    lnk = desktop_lnk()
    if not on:
        if os.path.exists(lnk):
            os.remove(lnk)
        return
    me = os.path.abspath(__file__)
    env = {**os.environ, "K_LNK": lnk, "K_EXE": pythonw(), "K_ARGS": f'"{me}"', "K_ICON": icon_path(), "K_DIR": os.path.dirname(me)}
    ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:K_LNK); $s.TargetPath = $env:K_EXE; "
          "$s.Arguments = $env:K_ARGS; $s.IconLocation = $env:K_ICON; $s.WorkingDirectory = $env:K_DIR; "
          "$s.Description = 'Kemper (Key Mapper)'; $s.Save()")  # paths go in via env vars, never pasted into the script
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env,
                       capture_output=True, creationflags=0x08000000)  # CREATE_NO_WINDOW
    if r.returncode or not os.path.exists(lnk):
        raise OSError(r.stderr.decode(errors="replace").strip() or "couldn't create the shortcut")

# ---------- window helpers ----------
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

def dark_title_bar(dark):
    hwnd = own_window()
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
        return {**self._cfg, "startup": startup_enabled(), "desktop": desktop_enabled(), "notice": self._notice}

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
            if self._picker:
                self._picker.destroy()
            self._window.destroy()

    def _on_closing(self):
        if self._quitting:
            return True
        self._window.hide()  # closing only hides; hotkeys keep working
        return False

    # --- quick picker (like Win+V for the clipboard, but for your shortcuts) ---
    def _open_picker(self):
        if not self._picker:
            return
        if self._picker_open:  # the picker combo again closes it
            return self.close_picker(True)
        self._picker_target = user32.GetForegroundWindow()
        self._picker.evaluate_js("openPicker()")
        hwnd = own_window(PICKER_TITLE)
        if hwnd:
            place_popup(hwnd)
        self._picker.show()
        if hwnd:
            user32.SetForegroundWindow(hwnd)  # allowed: we just received the hotkey
        self._picker_open = True

    def picker_items(self):
        a = self._cfg["appearance"]
        return {"items": [{"i": i, "text": m["text"], "label": combo_label(m)} for i, m in enumerate(self._cfg["mappings"])],
                "dark": a == "dark" or (a == "system" and os_is_dark())}

    def close_picker(self, refocus=False):
        if not (self._picker and self._picker_open):
            return
        self._picker_open = False
        self._picker.hide()
        if refocus and self._picker_target:
            user32.SetForegroundWindow(self._picker_target)

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
                try:
                    cmd = conn.recv(16)
                except OSError:
                    cmd = b""
            if cmd == b"quit":
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
               "win": "Win", "windows": "Win", "meta": "Win", "super": "Win"}
NAMED_KEYS = {"space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
              "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D, "home": 0x24,
              "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
              "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}
user32.VkKeyScanW.argtypes = (wintypes.WCHAR,)  # without this ctypes passes a pointer, not the char
user32.VkKeyScanW.restype = ctypes.c_short

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
    k = key.lower()
    if k in NAMED_KEYS:
        vk = NAMED_KEYS[k]
    elif re.fullmatch(r"f([1-9]|1\d|2[0-4])", k):
        vk = 0x6F + int(k[1:])
    elif re.fullmatch(r"num[0-9]", k):
        vk = 0x60 + int(k[3:])
    elif len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key.upper())
    elif len(key) == 1 and (r := user32.VkKeyScanW(key)) != -1:
        vk = r & 0xFF
        if r >> 8:  # the character itself needs Shift/Ctrl/Alt on this keyboard layout
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
        description="Kemper (Key Mapper): press a key combo, get a character or text typed, anywhere in Windows.\n"
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
                   help="put a Kemper shortcut, with Kemper's icon, on the desktop, or remove it")
    g.add_argument("--status", action="store_true", help="show whether Kemper is running and how it is set up")
    g.add_argument("--doctor", action="store_true", help="check for problems and say how to fix each one")
    g.add_argument("--show", action="store_true", help="open the window (starts Kemper if it isn't running)")
    g.add_argument("--quit", action="store_true", help="stop the running Kemper, window or --cli")
    g.add_argument("--autostart", choices=["on", "off"],
                   help="start Kemper when you sign in to Windows, or stop doing so (same as the switch in the window)")
    g.add_argument("--uninstall", action="store_true",
                   help="remove Kemper from this PC: stop it, remove it from startup, delete your settings and this file")
    g.add_argument("--hidden", action="store_true", help="open with the window hidden (used when Windows starts)")
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
    try:
        set_desktop(on)
    except OSError as e:
        fail(f"Couldn't create the desktop shortcut: {e}")
    print(f"Added Kemper to your desktop ({desktop_lnk()})." if on else "Removed Kemper from your desktop.")

def cmd_status():
    cfg = load()
    running = send_command(b"ping")
    print(f"Kemper {VERSION}")
    print(f"  Running:             {'yes' if running else 'no'}")
    print(f"  Shortcuts:           {len(cfg['mappings'])} ({'active' if cfg['active'] else 'deactivated'})")
    print(f"  {picker_line(cfg).replace(': ', ':        ')}")
    print(f"  Start with Windows:  {'on' if startup_enabled() else 'off'}")
    print(f"  Desktop shortcut:    {'yes' if desktop_enabled() else 'no'}")
    print(f"  Settings file:       {CONFIG}")
    print(f"  Program file:        {os.path.abspath(__file__)}")

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

def hotkey_free(m):
    hid = 0xBFFF
    if user32.RegisterHotKey(None, hid, hotkey_flags(m), m["vk"]):
        user32.UnregisterHotKey(None, hid)
        return True
    return False

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
    wv2 = webview2_version()
    check(0 if wv2 else 1, f"Edge WebView2 {wv2} (draws the window)" if wv2 else
          "Edge WebView2 not found, so the window may not open. Get it from https://go.microsoft.com/fwlink/p/?LinkId=2124703")

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
          "Kemper isn't running, so shortcuts do nothing. Start it:  pythonw kemper.pyw  (or --cli)")

    sv = startup_value()
    if sv is None:
        check(1, "Kemper doesn't start with Windows. Fix:  python kemper.pyw --autostart on")
    elif sv == startup_cmd():
        check(0, "Starts with Windows")
    else:
        check(2, "The Windows startup entry points to a different place (was Kemper moved?). Fix:  python kemper.pyw --autostart on")

    if running:
        check(0, "Skipped the hotkey check because the running Kemper is holding them")
    else:
        combos = cfg["mappings"] + ([cfg["picker"]] if cfg["picker"]["enabled"] else [])
        taken = [combo_label(m) for m in combos if not hotkey_free(m)]
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
    subprocess.Popen([pythonw(), os.path.abspath(__file__)], close_fds=True)

def cmd_show():
    if send_command(b"show"):
        return
    start_gui_process()
    print("Started Kemper.")

def cmd_quit():
    print("Kemper stopped." if send_command(b"quit") else "Kemper isn't running.")

def cmd_autostart(on):
    set_startup(on)
    print("Kemper will start when you sign in to Windows." if on else "Kemper won't start with Windows anymore.")

def cmd_uninstall(yes):
    me = os.path.abspath(__file__)
    if not yes:
        print("This stops Kemper, removes it from Windows startup and the desktop, deletes your shortcuts and settings,")
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
    print("Removed Kemper from Windows startup.")
    if desktop_enabled():
        set_desktop(False)
        print("Removed the desktop shortcut.")
    folder = os.path.dirname(CONFIG)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
        print(f"Deleted your shortcuts and settings ({folder}).")
    os.remove(me)
    print(f"Deleted {me}.\nKemper is uninstalled.")

def run_gui(hidden):
    srv = claim_instance()
    if not srv:  # already running: bring that window up instead
        send_command(b"show")
        return
    try:
        import webview  # imported here so the CLI works without it
    except ImportError:
        if hidden:  # started with Windows but can't draw a window: still run the shortcuts
            api = Api()
            serve(srv, api)
            api._done.wait()
            return
        user32.MessageBoxW(None, "Kemper's window needs pywebview. Install it with:\n\n    python -m pip install pywebview\n\n"
                                 "Or use Kemper without a window:\n\n    python kemper.pyw --cli", APP, 0x10)
        return
    api = Api()
    serve(srv, api)
    cfg = api._cfg
    dark = cfg["appearance"] == "dark" or (cfg["appearance"] == "system" and os_is_dark())
    win = webview.create_window(APP, html=UI_HTML, js_api=api, width=540, height=680, min_size=(440, 480),
                                hidden=hidden, background_color="#000000" if dark else "#F2F2F7", text_select=True)
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
    # own taskbar identity, so Windows shows Kemper's icon instead of grouping it under Python
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Kemper.KeyMapper")
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
      <div class="label">Start with Windows</div>
      <label class="switch"><input type="checkbox" id="startup" aria-label="Start with Windows"><span></span></label>
    </div>
    <div class="row">
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
  <div class="section-foot">Press it in any app to see all your shortcuts and pick one, like Win + V does for the clipboard.</div>

  <div class="section-title">Key → Text</div>
  <div class="card" id="list"></div>
  <div class="section-foot" id="hint">Click a key box, then press the combo, like Alt + 2. Paste or type the text it should produce, like ².</div>
</main>
<footer>
  <div id="status"></div>
  <button id="save" disabled>Save</button>
</footer>

<script>
let api, rows = [], picker = null, saved = "", notice = "", recording = null, appearance = "system", active = true;
const $ = s => document.querySelector(s);
const ORDER = ["Ctrl", "Alt", "Shift", "Win"];
const MOD_KEYS = ["Control", "Alt", "Shift", "Meta", "AltGraph", "OS"];
const media = matchMedia("(prefers-color-scheme: dark)");

const id = r => [...r.mods].sort().join("+") + "|" + r.vk;
const label = r => [...r.mods].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b)).concat(r.key).join(" + ");
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
  else { msg = "You have unsaved changes."; ok = true; }
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
  active = s.active;
  showActive();
  applyTheme(false);
  render();
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
