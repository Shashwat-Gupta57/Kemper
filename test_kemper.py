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

# --- quick picker: its combo can't also be a shortcut ---
picker = k.clean_picker({"enabled": True, "mods": ["Alt", "Ctrl"], "vk": 0x4B, "key": "K"})
assert picker["mods"] == ["Ctrl", "Alt"]
ctrl_alt_k = {"mods": ["Ctrl", "Alt"], "vk": 0x4B, "key": "K", "text": "k"}
try:
    k.clean_mappings([ctrl_alt_k], picker)
    raise AssertionError("shortcut on the picker combo was accepted")
except ValueError:
    pass
assert k.clean_mappings([ctrl_alt_k], {**picker, "enabled": False})  # fine once the picker is off
for bad in ({**picker, "vk": 0}, {**picker, "enabled": "yes"}, None):
    try:
        k.clean_picker(bad)
        raise AssertionError(f"accepted picker {bad}")
    except ValueError:
        pass

# --- keypacks: files, names, validation and the import preview ---
tmp = tempfile.mkdtemp()
pack_path = os.path.join(tmp, "whatever-file-name.kmppck")
assert k.write_keypack(pack_path, "  Math symbols ", [b, a]) == "Math symbols"
pack = k.read_keypack(pack_path)
assert pack["name"] == "Math symbols"  # the name lives in the file, not in the file name
assert [m["text"] for m in pack["mappings"]] == ["₂", "²"]
for bad_args in (("", [a]), ("X", []), ("X", [a, {**a, "text": "dup"}]), ("X", [empty])):
    try:
        k.write_keypack(os.path.join(tmp, "no.kmppck"), *bad_args)
        raise AssertionError(f"wrote keypack {bad_args}")
    except ValueError:
        pass
assert not os.path.exists(os.path.join(tmp, "no.kmppck"))

def bad_file(content, expect):
    p = os.path.join(tmp, "bad.kmppck")
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        k.read_keypack(p)
        raise AssertionError(f"read {content[:40]!r}")
    except ValueError as e:
        assert expect in str(e), str(e)

bad_file("not json", "isn't a Kemper keypack")
bad_file('{"mappings": []}', "isn't a Kemper keypack")
bad_file('{"format": "kemper-keypack", "version": 2, "mappings": []}', "newer Kemper")
bad_file('{"format": "kemper-keypack", "version": 1, "mappings": [{"mods": ["Alt"], "vk": 999, "key": "2", "text": "x"}]}', "Shortcut 1")
bad_file('{"format": "kemper-keypack", "version": 1, "mappings": [{"mods": ["Alt"], "vk": 50, "key": "2", "text": "' + "x" * 10_001 + '"}]}', "Shortcut 1")
bad_file(" " * (k.KEYPACK_MAX_BYTES + 1), "too big")
nameless = os.path.join(tmp, "Arrows.kmppck")
with open(nameless, "w", encoding="utf-8") as f:
    json.dump({"format": "kemper-keypack", "version": 1, "mappings": [a]}, f)
assert k.read_keypack(nameless)["name"] == "Arrows"  # no name inside: fall back to the file name

cfg = {"mappings": [a, {"mods": ["Ctrl", "Alt"], "vk": 69, "key": "E", "text": "€"}], "picker": picker}
pack_maps = [
    a,                                                                  # same combo, same text: already there
    {"mods": ["Ctrl", "Alt"], "vk": 69, "key": "E", "text": "E!"},      # clashes with my €
    {"mods": ["Alt"], "vk": 0x33, "key": "3", "text": "³"},             # twice in the pack
    {"mods": ["Alt"], "vk": 0x33, "key": "3", "text": "3rd"},
    {"mods": ["Ctrl", "Alt"], "vk": 0x4B, "key": "K", "text": "k"},     # the quick picker's combo
    {"mods": ["Ctrl"], "vk": ord("C"), "key": "C", "text": "©"},        # takes over copy
    {"mods": ["Shift"], "vk": ord("A"), "key": "A", "text": "α"},       # takes over typing
    {"mods": ["Alt"], "vk": 0x34, "key": "4", "text": "⁴"},             # fine
]
levels = [(i["level"], i["issue"]) for i in k.keypack_preview(pack_maps, cfg)]
assert [l for l, _ in levels] == ["same", "bad", "bad", "bad", "bad", "warn", "warn", ""], levels
assert "€" in levels[1][1] and "quick picker" in levels[4][1] and "Ctrl + C" in levels[5][1]

# --- keypacks written by AI: readable "keys" form, chatter around the JSON, the instructions themselves ---
reply = '''Sure! Here's your keypack:

```json
{"format": "kemper-keypack", "version": 1, "name": "Arrows",
 "mappings": [{"keys": "Ctrl + Alt + Left", "text": "←"}, {"keys": "ctrl+alt+right", "text": "→"},
              {"keys": "Alt+Shift+Page Up", "text": "⇞"}, {"mods": ["Alt"], "vk": 53, "key": "5", "text": "⁵"}]}
```

| Press | Types |
|---|---|
| Ctrl+Alt+Left | ← |'''
arrows = k.parse_keypack(reply)
assert arrows["name"] == "Arrows" and [m["vk"] for m in arrows["mappings"]] == [0x25, 0x27, 0x21, 0x35]
assert arrows["mappings"][0]["mods"] == ["Ctrl", "Alt"]
for text, expect in (('{"format": "kemper-keypack", "mappings": [{"keys": "Alt+Banana", "text": "x"}]}', "Shortcut 1 (Alt+Banana)"),
                     ('{"format": "kemper-keypack", "mappings": [{"keys": "Alt+2"}]}', "Shortcut 1 (Alt+2)"),
                     ("Sorry, I can't help with that.", "isn't a Kemper keypack")):
    try:
        k.parse_keypack(text)
        raise AssertionError(f"parsed {text!r}")
    except ValueError as e:
        assert expect in str(e), str(e)

example = k.AI_INSTRUCTIONS.split("```json")[-1].split("```")[0]  # the worked example at the end
greek = k.parse_keypack(example)
assert greek["name"] == "Greek letters for math" and len(k.clean_mappings(greek["mappings"])) == 5
with open(os.path.join(HERE, "docs", "AI_INSTRUCTIONS.md"), encoding="utf-8") as f:
    assert k.AI_INSTRUCTIONS in f.read(), "docs/AI_INSTRUCTIONS.md is out of sync with AI_INSTRUCTIONS in kemper.pyw"

k.write_keypack(pack_path, "Readable", [a, {"mods": ["Ctrl", "Alt"], "vk": 0x25, "key": "Left", "text": "←"}])
with open(pack_path, encoding="utf-8") as f:
    assert json.load(f)["mappings"] == [{"keys": "Alt+2", "text": "²"}, {"keys": "Ctrl+Alt+Left", "text": "←"}]
assert [m["vk"] for m in k.read_keypack(pack_path)["mappings"]] == [0x32, 0x25]
with open(pack_path, "w", encoding="utf-8-sig") as f:  # Notepad may save with a byte-order mark
    json.dump({"format": "kemper-keypack", "version": 1, "mappings": [{"keys": "Alt+2", "text": "²"}]}, f)
assert k.read_keypack(pack_path)["mappings"][0]["text"] == "²"

assert k.keypack_filename("  My Pack: 2/3?  ") == "My Pack 23.kmppck"
assert k.keypack_filename("pack.KMPPCK") == "pack.kmppck"
for bad_name in ("", "  ...  ", "CON", "lpt1"):
    try:
        k.keypack_filename(bad_name)
        raise AssertionError(f"accepted file name {bad_name!r}")
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

# --- icon: the embedded PNGs become a valid .ico (header: reserved 0, type 1, one entry per size) ---
k.CONFIG = os.path.join(env["APPDATA"], "Kemper", "mappings.json")
ico = open(k.icon_path(), "rb").read()
assert ico[:4] == b"\0\0\1\0" and int.from_bytes(ico[4:6], "little") == len(k.ICON_PNGS)
assert ico[6 + 16 * len(k.ICON_PNGS):][:8] == b"\x89PNG\r\n\x1a\n"

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
code, out = cli("--add", "Ctrl+Alt+K", "k")  # the picker's default combo
assert code == 1 and "opens the quick picker" in out, out
code, out = cli("--picker", "Ctrl+Alt+P")
assert code == 0 and "Quick picker: Ctrl + Alt + P" in out, out
assert cli("--add", "Ctrl+Alt+K", "k")[0] == 0  # free now
code, out = cli("--picker", "ctrl+alt+k")  # now clashes with that shortcut
assert code == 1 and "quick picker" in out, out
code, out = cli("--picker", "off")
assert code == 0 and "Quick picker: off" in out and "Quick picker: off" in cli("--keys")[1], out
code, out = cli("--help")
assert code == 0 and "--doctor" in out and "--cli" in out
print("ok")
