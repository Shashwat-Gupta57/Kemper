"""Kemper (Key Mapper): press a key combo (e.g. Alt+2), get a character or text (e.g. ²) typed anywhere in Windows.

One file. Run it to open the window, or see every command with:  python kemper.pyw --help
https://github.com/Shashwat-Gupta57/Kemper  ·  MIT License
"""
import argparse, ctypes, json, os, re, shutil, socket, subprocess, sys, threading, time, winreg

from ctypes import wintypes

APP = "Kemper"
VERSION = "1.0.0"
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
        return {**self._cfg, "startup": startup_enabled(), "notice": self._notice}

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

def cmd_status():
    cfg = load()
    running = send_command(b"ping")
    print(f"Kemper {VERSION}")
    print(f"  Running:             {'yes' if running else 'no'}")
    print(f"  Shortcuts:           {len(cfg['mappings'])} ({'active' if cfg['active'] else 'deactivated'})")
    print(f"  {picker_line(cfg).replace(': ', ':        ')}")
    print(f"  Start with Windows:  {'on' if startup_enabled() else 'off'}")
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
        print("This stops Kemper, removes it from Windows startup, deletes your shortcuts and settings, and deletes")
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
    webview.start()

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

if __name__ == "__main__":
    main()
