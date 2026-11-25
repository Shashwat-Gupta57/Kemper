"""Self-checks for Kemper. Run:  python test_kemper.py   (Windows only, needs no GUI)."""
import importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.join(HERE, "kemper.pyw")
loader = importlib.machinery.SourceFileLoader("kemper", PROGRAM)
spec = importlib.util.spec_from_loader("kemper", loader)
k = importlib.util.module_from_spec(spec)
loader.exec_module(k)

# --- conflicts ---
a = {"mods": ["Alt"], "vk": 0x32, "key": "2", "text": "²"}
b = {"mods": ["Shift", "Alt"], "vk": 0x32, "key": "2", "text": "₂"}
c = {"mods": ["Alt", "Shift"], "vk": 0x32, "key": "2", "text": "x"}  # same combo as b, different order
empty = {"mods": [], "vk": 0, "key": "", "text": ""}

assert k.find_conflicts([a, b]) == set()
assert k.find_conflicts([a, b, c]) == {k.combo_id(b)}
assert k.find_conflicts([empty, empty]) == set()  # unset rows aren't conflicts
assert k.combo_label(b) == "Alt + Shift + 2"

# --- typing ---
assert k.utf16_units("²") == [0xB2]
assert k.utf16_units("😀") == [0xD83D, 0xDE00]  # emoji go through as surrogate pairs

# --- save-side validation: conflicts and incomplete rows can never be written ---
assert k.clean_mappings([b, a])[0]["mods"] == ["Alt", "Shift"]
for bad in ([a, b, c], [empty], [{**a, "mods": ["Hyper"]}], [{**a, "text": ""}]):
    try:
        k.clean_mappings(bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass

# --- combos typed as text ---
p = k.parse_combo
assert p("alt+shift+2") == {"mods": ["Alt", "Shift"], "vk": 0x32, "key": "2"}
assert p("Shift + Ctrl + e")["mods"] == ["Ctrl", "Shift"] and p("Shift + Ctrl + e")["vk"] == ord("E")
assert p("Ctrl+Alt+Right")["vk"] == 0x27
assert p("F5") == {"mods": [], "vk": 0x74, "key": "F5"}
assert p("Win+Num7")["vk"] == 0x67
assert p("Ctrl+-")["vk"] == 0xBD
assert k.combo_id(p("Alt+Shift+2")) == k.combo_id(b)
for bad in ("Hyper+2", "Alt+", "Alt+Banana", "F25", ""):
    try:
        p(bad)
        raise AssertionError(f"parsed {bad!r}")
    except ValueError:
        pass

# --- CLI, against a throwaway settings folder ---
env = {**os.environ, "APPDATA": tempfile.mkdtemp(), "PYTHONIOENCODING": "utf-8"}

def cli(*args):
    r = subprocess.run([sys.executable, PROGRAM, *args], env=env, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr

code, out = cli("--add", "Alt+2", "²")
assert code == 0 and "Added Alt + 2" in out, out
code, out = cli("--add", "alt+2", "x")  # same keys again
assert code == 1 and "already types ²" in out, out
code, out = cli("--keys")
assert code == 0 and "Alt + 2  →  ²" in out and "1 shortcut(s), active" in out, out
code, out = cli("--deactivate")
assert code == 0 and "deactivated" in cli("--keys")[1]
code, out = cli("--remove", "Alt+2")
assert code == 0 and "No shortcuts yet" in cli("--keys")[1], out
code, out = cli("--remove", "Alt+2")
assert code == 1 and "No shortcut uses" in out, out
saved = json.load(open(os.path.join(env["APPDATA"], "Kemper", "mappings.json"), encoding="utf-8"))
assert saved["mappings"] == [] and saved["active"] is False
code, out = cli("--help")
assert code == 0 and "--doctor" in out and "--cli" in out
print("ok")
