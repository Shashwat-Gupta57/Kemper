import importlib.machinery, importlib.util, os

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kemper.pyw")
loader = importlib.machinery.SourceFileLoader("kemper", path)
spec = importlib.util.spec_from_loader("kemper", loader)
k = importlib.util.module_from_spec(spec)
loader.exec_module(k)

a = {"mods": ["Alt"], "vk": 0x32, "key": "2", "text": "²"}
b = {"mods": ["Shift", "Alt"], "vk": 0x32, "key": "2", "text": "₂"}
c = {"mods": ["Alt", "Shift"], "vk": 0x32, "key": "2", "text": "x"}  # same combo as b, different order
empty = {"mods": [], "vk": 0, "key": "", "text": ""}

assert k.find_conflicts([a, b]) == set()
assert k.find_conflicts([a, b, c]) == {k.combo_id(b)}
assert k.find_conflicts([empty, empty]) == set()  # unset rows aren't conflicts
assert k.combo_label(b) == "Alt + Shift + 2"
assert k.utf16_units("²") == [0xB2]
assert k.utf16_units("😀") == [0xD83D, 0xDE00]  # emoji go through as surrogate pairs

# save-side validation: conflicts and incomplete rows can never be written
assert k.clean_mappings([b, a])[0]["mods"] == ["Alt", "Shift"]
for bad in ([a, b, c], [empty], [{**a, "mods": ["Hyper"]}], [{**a, "text": ""}]):
    try:
        k.clean_mappings(bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass
print("ok")
