"""Kemper: map key combos (e.g. Alt+2) to characters or strings that get typed anywhere."""
import ctypes, json, os, socket, sys, threading, time, winreg

from ctypes import wintypes

APP = "Kemper"
CONFIG = os.path.join(os.environ.get("APPDATA", "."), APP, "mappings.json")
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

def clean_mappings(rows):
    """Validate mappings coming from the UI; raises ValueError so a bad config is never saved."""
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
    return out

def load():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if isinstance(data, list):  # v1 config was a bare list
        data = {"mappings": data}
    return {"mappings": data.get("mappings", []), "appearance": data.get("appearance", "system")}

def save(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG)  # atomic, so a crash can't leave a half-written config

class Listener(threading.Thread):
    """Owns the global hotkeys. RegisterHotKey ties them to this thread's message queue."""
    def __init__(self, rows):
        super().__init__(daemon=True)
        self.rows, self.failed, self.ready = rows, [], threading.Event()

    def run(self):
        self.tid = kernel32.GetCurrentThreadId()
        for i, m in enumerate(self.rows):
            flags = MOD_NOREPEAT | sum(f for n, _, f in MODS if n in m["mods"])
            if not user32.RegisterHotKey(None, i + 1, flags, m["vk"]):
                self.failed.append(combo_label(m))
        self.ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and 0 < msg.wParam <= len(self.rows):
                type_text(self.rows[msg.wParam - 1]["text"])
        for i in range(len(self.rows)):
            user32.UnregisterHotKey(None, i + 1)

    def stop(self):
        user32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)
        self.join(2)

# ---------- start with Windows ----------
def startup_cmd():
    exe = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{exe}" "{os.path.abspath(__file__)}" --hidden'

def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, APP)[0] == startup_cmd()
    except OSError:
        return False

def set_startup(on):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, startup_cmd())
        else:
            try:
                winreg.DeleteValue(k, APP)
            except FileNotFoundError:
                pass

# ---------- UI bridge (the page lives in ui.html) ----------
def os_is_dark():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False

user32.FindWindowExW.restype = wintypes.HWND

def own_window():
    """Our top-level window. Matches by process too, since e.g. an Explorer folder can also be titled 'Kemper'."""
    hwnd = None
    while hwnd := user32.FindWindowExW(None, hwnd, None, APP):
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

class Api:
    """Methods here are callable from JS as window.pywebview.api.<name>. Underscored attrs stay private."""
    def __init__(self):
        self._cfg = load()
        self._listener = None
        self._lock = threading.Lock()
        self._window = None
        self._quitting = False
        self._notice = ""
        self._start()

    def _start(self):
        with self._lock:
            if self._listener:
                return
            self._listener = Listener([dict(m) for m in self._cfg["mappings"]])
            self._listener.start()
            self._listener.ready.wait(2)
            failed = self._listener.failed
            self._notice = ("Already used by another app, so these won't work: " + ", ".join(failed)) if failed else ""

    def _stop(self):
        with self._lock:
            if self._listener:
                self._listener.stop()
                self._listener = None

    def state(self):
        return {**self._cfg, "startup": startup_enabled(), "notice": self._notice}

    def key_name(self, vk):
        return key_name(int(vk))

    def capture(self, on):
        # Hotkeys are paused while recording so pressing an existing combo doesn't type its text.
        self._stop() if on else self._start()

    def save(self, rows):
        try:
            mappings = clean_mappings(rows)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        self._cfg["mappings"] = mappings
        save(self._cfg)
        self._stop()
        self._start()
        return {"ok": True, "mappings": mappings, "notice": self._notice}

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

    def quit(self):
        self._quitting = True
        self._window.destroy()

    def _on_closing(self):
        if self._quitting:
            return True
        self._window.hide()  # closing only hides; hotkeys keep working
        return False

def main():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        srv.bind(("127.0.0.1", PORT))
    except OSError:  # already running: bring that window up instead
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=2).close()
        except OSError:
            pass
        return
    srv.listen()

    import webview  # imported late so the tests and the second-instance path stay fast
    api = Api()
    cfg = api._cfg
    dark = cfg["appearance"] == "dark" or (cfg["appearance"] == "system" and os_is_dark())
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.html"), encoding="utf-8") as f:
        html = f.read()
    win = webview.create_window(APP, html=html, js_api=api, width=540, height=680, min_size=(440, 480),
                                hidden="--hidden" in sys.argv, background_color="#000000" if dark else "#F2F2F7",
                                text_select=True)
    api._window = win
    win.events.closing += api._on_closing
    win.events.shown += lambda: dark_title_bar(dark)

    def serve():
        while True:
            srv.accept()[0].close()
            win.show()
            win.restore()
    threading.Thread(target=serve, daemon=True).start()
    webview.start()

if __name__ == "__main__":
    main()
