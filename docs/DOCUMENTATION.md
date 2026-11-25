# Kemper documentation

Kemper (Key Mapper) types a character or text when you press a key combo, in any Windows app. This page covers everything in detail. For a quick start, see the [README](../README.md).

- [Requirements](#requirements)
- [Getting started](#getting-started)
- [The window](#the-window)
- [Quick picker](#quick-picker)
- [Keypacks](#keypacks)
- [Command line reference](#command-line-reference)
- [Writing combos](#writing-combos)
- [What text can be typed](#what-text-can-be-typed)
- [Settings file](#settings-file)
- [Running in the background and at startup](#running-in-the-background-and-at-startup)
- [Uninstalling](#uninstalling)
- [How Kemper works](#how-kemper-works)
- [Troubleshooting](#troubleshooting)
- [Limits](#limits)
- [Development](#development)

## Requirements

Kemper runs on **Windows 10 and 11**, **macOS** and **Linux with an X11 session**. All of them need [Python 3.10 or newer](https://www.python.org/downloads/) (on Windows, tick *Add python.exe to PATH* when installing).

| System | Needed for the shortcuts | Needed for the window |
|---|---|---|
| Windows | nothing extra | [pywebview](https://pywebview.flowrl.com/), plus Edge WebView2 (built into Windows 11 and current Windows 10; [download](https://go.microsoft.com/fwlink/p/?LinkId=2124703) if `--doctor` says it's missing) |
| macOS | [pynput](https://pypi.org/project/pynput/), and Accessibility and Input Monitoring permission | pywebview |
| Linux | [python-xlib](https://pypi.org/project/python-xlib/), and an X11 (Xorg) session | pywebview, plus GTK's WebKit (`gir1.2-webkit2-4.1`) |

The command line, including `--cli`, never needs pywebview.

## Getting started

Kemper is a single file, `kemper.pyw`. There's no installer: put it in a folder where it can stay and run it.

**Windows**
1. Install the window's library: `python -m pip install pywebview`
2. Double-click `kemper.pyw`.
3. To have Kemper running every time you sign in, turn on **Start with Windows** in the window.
4. To get Kemper's icon on your desktop, turn on **Desktop shortcut**. Windows always draws a `.pyw` file with Python's icon, and a script can't carry an icon of its own, so Kemper puts its icon on a shortcut instead.

**macOS**

```bash
python3 -m venv ~/.kemper
~/.kemper/bin/pip install pywebview pynput
~/.kemper/bin/python kemper.pyw
```

macOS asks for **Input Monitoring** and **Accessibility** the first time. Allow the app you started Kemper from (Terminal, or Python itself) in System Settings → Privacy & Security, then start Kemper again. If shortcuts work from Terminal but not after you sign in, also add the Python app there, since that's what runs Kemper at login. Turn on **Start at login** in the window if you want it.

**Ubuntu and other Linux**

```bash
sudo apt install python3-venv python3-gi gir1.2-webkit2-4.1 xclip
python3 -m venv --system-site-packages ~/.kemper
~/.kemper/bin/pip install pywebview python-xlib
~/.kemper/bin/python kemper.pyw
```

`--system-site-packages` lets the environment use the GTK bindings apt installed. Kemper needs an **X11 session**: at Ubuntu's login screen, click the gear and choose **"Ubuntu on Xorg"**. Then turn on **Start at login** and **Desktop shortcut** in the window if you want them.

**Command line only:** pywebview isn't needed on any system. Use `kemper.pyw --cli` to run Kemper in a terminal and `--autostart on` to start it when you sign in. If pywebview is missing, Kemper still runs your shortcuts at sign-in, just without a window.

Starting at sign-in points at the exact path of `kemper.pyw` and the Python that ran it. If you move the file, switch **Start at login** (or **Start with Windows**) off and on again, or run `--autostart on` from the new place. `--doctor` warns you if the startup entry points to an old location.

### Differences between systems

| | Windows | macOS | Linux (X11) |
|---|---|---|---|
| Shortcuts, typing, quick picker, keypacks, CLI | ✓ | ✓ | ✓ |
| Start at sign-in | ✓ (Run key) | ✓ (LaunchAgent) | ✓ (autostart entry) |
| Desktop shortcut with Kemper's icon | ✓ | — | ✓ (desktop and app menu) |
| Double-click `.kmppck` to import | ✓ | — (use **Import a keypack…**) | ✓ |
| Modifier names in the window | Ctrl, Alt, Shift, Win | Ctrl, Option, Shift, Cmd | Ctrl, Alt, Shift, Super |

macOS only gives desktop icons and file types to real, signed app bundles, which a single script can't be.

Settings and keypacks are identical on every system. Kemper always stores the fourth modifier as `Win`, so a keypack made on Windows with Win + K is Cmd + K on a Mac and Super + K on Linux. When you type combos on the command line you can write `Cmd`, `Option` or `Super` too.

## The window

Open it by running `kemper.pyw` (double-click works), or with `python kemper.pyw --show`.

| Part | What it does |
|---|---|
| **Deactivate / Activate** | Turns every shortcut off or back on. Kemper stays running, and the choice is remembered after a restart |
| **Quit** | Stops Kemper completely. Shortcuts stop working until you start it again |
| **Start with Windows** (**Start at login** on macOS and Linux) | Starts Kemper, hidden, every time you sign in |
| **Desktop shortcut** | Puts a *Kemper* shortcut, with Kemper's icon, on your desktop. Double-clicking it opens Kemper |
| **Appearance** | System follows your Windows light or dark setting as it changes. Light and Dark force one look |
| **Quick picker** switch | Turns the [quick picker](#quick-picker) on or off |
| **Open it with** | The quick picker's combo. Click it and press new keys to change it. Default: Ctrl + Alt + K |
| **Key box** | Click it, then press a combo. Esc or clicking elsewhere cancels |
| **Text field** | What the combo types. Paste anything, including emoji |
| **Red minus** | Deletes that shortcut |
| **Add Shortcut** | Adds a row and starts recording its combo right away |
| **Save** (Ctrl + S) | Saves and applies your changes. It's only enabled when there's something valid to save |

**Conflicts.** When two shortcuts use the same keys, both rows turn red and Save stays disabled until you change one of them. The quick picker's combo counts too: a shortcut can't use it while the picker is on. Modifier order doesn't matter: Alt + Shift + 2 and Shift + Alt + 2 are the same combo.

**Closing the window** only hides it. Shortcuts keep working. Running `kemper.pyw` again brings the window back instead of starting a second copy.

While you record a combo, Kemper pauses all shortcuts, so pressing an existing combo records it instead of typing its text.

## Quick picker

The quick picker is for shortcuts you don't remember. Press its combo (**Ctrl + Alt + K** by default) in any app, and a small panel opens by your mouse with all your shortcuts. It works like **Win + V** does for the clipboard.

| Do this | To |
|---|---|
| Type | Filter by the text or by the combo's name (`2`, `alt`, `€`) |
| ↑ ↓, or hover | Move the highlight |
| Enter, or click | Type the highlighted text into the app you were in |
| Esc, click elsewhere, or press the combo again | Close it without typing anything |
| Drag the top strip (the one with the small handle) | Move the panel |

The panel opens near the mouse each time, kept on screen, and doesn't show in the taskbar. It follows your Appearance setting.

Change its combo in the window (**Quick Picker → Open it with**), or with `python kemper.pyw --picker "Ctrl+Alt+P"`. Turn it off with the switch or `--picker off`.

The picker is part of the window version of Kemper. It isn't available in `--cli` mode, which has no window.

## Keypacks

A keypack is a set of shortcuts saved in one `.kmppck` file so it can be shared: by email, in a chat, on a website. Anyone with Kemper can import it.

### Importing a keypack

Double-click a `.kmppck` file, or use **Keypacks → Import a keypack…** at the bottom of Kemper's window, or run `python kemper.pyw --keypack FILE`. Kemper opens (or comes to the front, if it's already running) and asks whether to import it.

The question shows the keypack's name, its file and every shortcut in it, with what importing would do:

| Mark | Meaning | What import does |
|---|---|---|
| Red | Clashes with one of your shortcuts, with your quick picker, or with another shortcut in the keypack | Adds it. Both rows turn red in your list |
| Orange | Takes over a key you probably use a lot: a Ctrl + letter that apps rely on (copy, paste, save, …) or a key with no modifier but Shift | Adds it. Check whether you really want it |
| Gray | You already have exactly this shortcut | Skips it |
| *none* | New and clash-free | Adds it |

**Conflicts don't stop the import; they stop saving.** After importing, the new shortcuts are in your list but not saved yet, exactly like ones you add by hand. If any are red, Save stays disabled until you change their keys or remove them. Click Cancel to import nothing.

### Making a keypack

1. At the bottom of Kemper's window, click **Keypacks → Create a keypack**.
2. Choose **New keypack** to start empty, or **Edit a keypack file…** to open an existing `.kmppck` and change it.
3. The **Keypack Editor** opens in its own window:

| Control | What it does |
|---|---|
| **Import** (top left) | Shows your Kemper shortcuts as a gallery. Click tiles to pick them, use **Select all** / **Deselect all**, then **Add**. Shortcuts already in the keypack are greyed out |
| **✦ AI** | Lets an AI chat write shortcuts for you. See [Making keypacks with AI](#making-keypacks-with-ai) |
| **Add** (Ctrl + N) | Adds a shortcut and starts recording its combo. Press the keys, then type its text |
| **Remove** (Delete) | Removes the selected shortcut. Click a row to select it |
| **Undo** (Ctrl + Z), **Redo** (Ctrl + Y) | Steps back and forth through your last 50 changes. Typing in one text box counts as one change until you pause |
| **Export** (Ctrl + S) | Saves the keypack as a file |

4. Click **Export** and fill in:
   - **Keypack name:** what people see when they import it, for example *Math symbols*.
   - **File name:** the `.kmppck` file's name. It starts out matching the keypack name, but you can change it; the name inside the file stays the same.
   - **Folder:** where to save it. Click **Choose…** to pick one. Kemper asks before replacing a file that's already there.

Like Kemper itself, the editor won't export while shortcuts clash or are missing keys or text. If you close the editor with changes you haven't exported, it asks first.

### Making keypacks with AI

Any AI chat (ChatGPT, Claude, Gemini, Copilot, …) can write a keypack from a plain description. Kemper includes instructions that teach the AI the format, the key names, which combos to avoid, and that every combo must be different.

1. Open the AI helper in either of two ways:
   - Click **✦ AI** in the Keypack Editor.
   - In Kemper's window, choose **Keypacks → Create a keypack → Make one with AI…**.
2. Click **Copy instructions** and paste them into a new AI chat. **Show** displays them first.
3. Tell the AI what you want, for example *"subscript digits on Alt+Shift+0 to 9"* or *"my standard email replies on Ctrl+Alt+1 to 5"*.
4. Copy the AI's whole answer, paste it into step 3 of the dialog, and click **Add to keypack**.

Kemper picks the keypack out of the answer, so any chat text or code fences around it don't matter. It then checks every shortcut:
- **Broken ones** are refused with a message naming them, for example *Shortcut 3 (Alt+Banana) in this keypack is broken: Unknown key 'Banana'*.
- **Clashing ones** show in red.

Everything lands in the editor, where you can change it, undo it, export it or import it into your Kemper.

The same instructions are in [AI_INSTRUCTIONS.md](AI_INSTRUCTIONS.md), with a copy button on GitHub, and `python kemper.pyw --ai-instructions` prints them. You can also save the AI's JSON as a `.kmppck` file and double-click it.

### The .kmppck file format

A keypack is a UTF-8 JSON file:

```json
{
  "format": "kemper-keypack",
  "version": 1,
  "name": "Math symbols",
  "made_with": "Kemper 3.0.0",
  "mappings": [
    { "keys": "Alt+2", "text": "²" },
    { "keys": "Alt+Shift+2", "text": "₂" },
    { "mods": ["Alt"], "vk": 107, "key": "Num +", "text": "±" }
  ]
}
```

| Field | Meaning |
|---|---|
| `format` | Always `"kemper-keypack"` |
| `version` | `1`. Optional; Kemper assumes 1 |
| `name` | What people see when importing. Optional; without it, Kemper uses the file name |
| `made_with` | Informational only |
| `mappings` | The shortcuts, in either of two forms |

Each shortcut takes one of two forms:
- **Readable:** `{ "keys": "Ctrl+Alt+E", "text": "€" }`. `keys` uses the [combo syntax](#writing-combos), so case and spaces don't matter. This is what Kemper writes, and what people and AI should write.
- **Exact:** `{ "mods": [...], "vk": ..., "key": ..., "text": ... }`, the same fields as the [settings file](#settings-file). Kemper writes it only for the rare key that has no readable name, like the number pad's `+`.

Kemper refuses a keypack that:
- is bigger than 1 MB
- isn't valid JSON or lacks `"format": "kemper-keypack"`
- comes from a newer version of the format
- has more than 1,000 shortcuts
- has a broken shortcut, or text longer than 10,000 characters

Text before or after the JSON object is ignored, so a copied AI reply works as it is.

### How .kmppck files open in Kemper

The first time Kemper's window runs, it registers the `.kmppck` file type for your user account: `HKEY_CURRENT_USER\Software\Classes\.kmppck` and `Kemper.Keypack`, with Kemper's icon. No admin rights are needed. It checks this on every start and fixes it if you've moved `kemper.pyw`. `--uninstall` removes it. `--doctor` tells you whether it's in place.

## Command line reference

Run commands with `python kemper.pyw <command>`. Use `python`, not `pythonw`: `pythonw` has no console, so you wouldn't see any output.

Commands that change settings (`--add`, `--remove`, `--picker`, `--activate`, `--deactivate`) also update a running Kemper immediately, whether it's the window or `--cli`.

### `--cli`

Runs Kemper in the terminal with no window. It logs each shortcut as you use it and reloads whenever you change settings from another terminal. Stop it with Ctrl+C, or `--quit` from another terminal.

```console
> python kemper.pyw --cli
Kemper 3.0.0 is running in this terminal (no window).
  2 shortcut(s) active. Each one shows up here when you use it.
  Press Ctrl+C to stop.

  Settings changed: 3 shortcut(s), active.
  13:19:58  Alt + 2  →  ²
```

Only one Kemper runs at a time. If the window version is already running, `--cli` says so and exits. Stop the other copy with `--quit` first.

### `--keys`

Lists your shortcuts. Line breaks in the text show as `⏎`.

```console
> python kemper.pyw --keys
  Alt + 2          →  ²
  Alt + Shift + 2  →  ₂

2 shortcut(s), active.
```

### `--add COMBO TEXT`

Adds a shortcut. Quote both values. Kemper refuses a combo that's already used and tells you which text it types.

```console
> python kemper.pyw --add "Ctrl+Alt+E" "€"
Added Ctrl + Alt + E  →  €
```

### `--remove COMBO`

Removes the shortcut with that combo. Spelling and modifier order don't need to match how you added it.

```console
> python kemper.pyw --remove "alt+ctrl+e"
Removed alt+ctrl+e.
```

### `--picker COMBO|on|off`

Sets the [quick picker](#quick-picker)'s combo, or turns the picker on or off. Kemper refuses a combo that a shortcut already uses.

```console
> python kemper.pyw --picker "Ctrl+Alt+P"
Quick picker: Ctrl + Alt + P

> python kemper.pyw --picker off
Quick picker: off
```

### `--activate`, `--deactivate`

Turns all shortcuts on or off without quitting Kemper. This is the same as the button in the window.

### `--status`

```console
> python kemper.pyw --status
Kemper 3.0.0
  Running:             yes
  Shortcuts:           2 (active)
  Quick picker:        Ctrl + Alt + K
  Start with Windows:  on
  Settings file:       C:\Users\you\AppData\Roaming\Kemper\mappings.json
  Program file:        C:\Tools\Kemper\kemper.pyw
```

### `--doctor`

Checks the setup and prints a fix for each problem. `✓` is fine, `!` is a warning, `✗` is a problem. It exits with code 1 if there's any `✗`, so scripts can use it.

It checks:
- the Python version
- that pywebview and WebView2 are present
- that the settings file is valid with no conflicts
- whether Kemper is active and running
- that the startup entry points to this file
- when Kemper isn't running, whether another app already owns any of your combos

### `--show`, `--quit`

`--show` opens the window of the running Kemper, or starts Kemper if it isn't running. `--quit` stops the running Kemper, whether it's the window or `--cli`.

### `--autostart on|off`

Starts Kemper when you sign in, or stops doing so. This is the same as the **Start with Windows** (or **Start at login**) switch in the window.

```console
> python kemper.pyw --autostart on
Kemper will start when you sign in.
```

### `--desktop on|off`

Adds or removes the desktop shortcut with Kemper's icon. This is the same as the **Desktop shortcut** switch.

```console
> python kemper.pyw --desktop on
Added Kemper to your desktop (C:\Users\you\Desktop\Kemper.lnk).
```

### `--ai-instructions`

Prints the instructions that teach an AI chat to write keypacks. See [Making keypacks with AI](#making-keypacks-with-ai).

### `--keypack FILE`

Opens a keypack in Kemper's window and asks whether to import it. This is what double-clicking a `.kmppck` file does. See [Keypacks](#keypacks).

### `--uninstall`

See [Uninstalling](#uninstalling).

### `--hidden`

Starts Kemper with its window hidden. Windows startup uses this so Kemper runs quietly when you log in.

### `-y`, `--yes`, `-v`, `--version`, `-h`, `--help`

`--yes` skips the confirmation question of `--uninstall`. `--version` prints the version. `--help` lists everything, with examples.

## Writing combos

Combos join keys with `+`. Case and spaces don't matter: `alt+shift+2`, `Alt + Shift + 2` and `Shift+Alt+2` are all the same combo.

**Modifiers:** `Ctrl` (or `Control`), `Alt`, `Shift`, `Win` (or `Windows`, `Meta`, `Super`).

**Keys:**

| Kind | Write |
|---|---|
| Letters, digits | `A`–`Z`, `0`–`9` |
| Function keys | `F1`–`F24` |
| Number pad | `Num0`–`Num9` |
| Named keys | `Space`, `Enter`, `Tab`, `Esc`, `Backspace`, `Delete`, `Insert`, `Home`, `End`, `PageUp`, `PageDown`, `Left`, `Right`, `Up`, `Down` |
| Punctuation | The character on the key, like `-` `=` `[` `]` `;` `'` `,` `.` `/` `` ` `` |

Punctuation follows your keyboard layout. A character that needs Shift, like `!`, isn't a key of its own, so write the key it's on: `Shift+1`. Kemper tells you this if you try.

A combo without a modifier (just `F9`, say) is allowed, but that key stops doing anything else everywhere while Kemper runs. Avoid plain letters and digits.

**Combos the system keeps for itself.** Some combos are already owned by the system or another app, for example many `Win + …` combos and `Ctrl + Alt + Delete` on Windows, or Super combos your Linux desktop uses. Kemper can't take those. The window shows a red notice naming them, and on Windows `--doctor` lists them. On macOS, Kemper sees keys before other apps do, so pick combos that don't clash with ones you use, like Cmd + C.

Punctuation keys follow your keyboard layout on Windows. On macOS and Linux, `--add` and keypacks name them as on a US keyboard; in the window you simply press the key.

## What text can be typed

Anything Unicode: accented letters, symbols, math (², ₂, ∑, √), arrows, emoji (😀), other scripts, and whole sentences. Kemper types it as text, so it works no matter which keyboard layout you use.

A line break in the text presses Enter. The window's text field is single-line, so add multi-line text by editing the [settings file](#settings-file) and writing `\n` in the JSON string.

## Settings file

Kemper keeps its settings in `mappings.json`, in each system's usual place:

| System | Folder |
|---|---|
| Windows | `%APPDATA%\Kemper` (usually `C:\Users\<you>\AppData\Roaming\Kemper`) |
| macOS | `~/Library/Application Support/Kemper` |
| Linux | `~/.config/kemper` (or `$XDG_CONFIG_HOME/kemper`) |

Set the `KEMPER_HOME` environment variable to use another folder. `--status` shows which one is in use.

```json
{
  "mappings": [
    { "mods": ["Alt"], "vk": 50, "key": "2", "text": "²" },
    { "mods": ["Alt", "Shift"], "vk": 50, "key": "2", "text": "₂" }
  ],
  "appearance": "system",
  "active": true,
  "picker": { "enabled": true, "mods": ["Ctrl", "Alt"], "vk": 75, "key": "K" }
}
```

| Field | Meaning |
|---|---|
| `mods` | Any of `Ctrl`, `Alt`, `Shift`, `Win` |
| `vk` | The key, as a Windows [virtual-key code](https://learn.microsoft.com/windows/win32/inputdev/virtual-key-codes) on every system (50 is `2`), so settings move between systems |
| `key` | The key's name, shown in the window |
| `text` | What gets typed |
| `appearance` | `system`, `light` or `dark` |
| `active` | `false` when Kemper is deactivated |
| `picker` | The quick picker: whether it's on, and its combo |

You can edit the file by hand. Afterwards, restart Kemper, or run any setting command so a running Kemper reloads it. Run `--doctor` to check your edit. Kemper never saves a file with conflicts or empty entries, and it saves atomically, so a crash can't leave a half-written file.

## Running in the background and at startup

- Closing the window hides it. Kemper keeps running until you click **Quit** or run `--quit`.
- Starting at sign-in runs `kemper.pyw --hidden` with the Python that set it up. No admin rights are needed, and only your user account is affected. Where it's recorded:

  | System | Entry |
  |---|---|
  | Windows | `Kemper` under `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` |
  | macOS | `~/Library/LaunchAgents/in.talken.kemper.plist` |
  | Linux | `~/.config/autostart/kemper.desktop` |

- Only one Kemper runs at a time. A second launch tells the first one to show its window, then exits.

Why not a *service* (or daemon)? Services run outside your desktop session, where they can't see your keyboard or type into your apps, so a hotkey tool can't be one. Starting at sign-in is the standard way to do it.

## Uninstalling

```powershell
python kemper.pyw --uninstall
```

After you confirm, Kemper:
1. stops the running Kemper,
2. removes its startup entry and its desktop shortcut, and unlinks `.kmppck` files,
3. deletes its [settings folder](#settings-file) (your shortcuts, settings and Kemper's icon file),
4. deletes `kemper.pyw` itself.

It touches nothing else; keypack files you've saved stay where they are. Python libraries stay installed because other programs may use them. If you made a `~/.kemper` environment on macOS or Linux, delete that folder too. Add `--yes` to skip the confirmation.

## How Kemper works

Kemper is one Python file. Besides the standard library it uses pywebview for the window, plus pynput on macOS and python-xlib on Linux. Everything that touches the operating system sits in one block per system, behind the same set of functions, so the rest of Kemper is identical everywhere. This section describes Windows first, then [what differs on macOS and Linux](#on-macos-and-linux).

```
 your key press ──► Windows hotkey (RegisterHotKey) ──► Kemper's listener thread
                                                              │
                         waits for you to release Alt/Ctrl/…  │
                                                              ▼
 text appears in your app ◄── SendInput, one Unicode character at a time
```

- **Hotkeys.** Each shortcut is registered with the Win32 [`RegisterHotKey`](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-registerhotkey) function on a dedicated thread. Windows delivers the combo to Kemper and swallows it, so the app you're in never sees it.
- **Typing.** When a combo fires, Kemper first taps an unassigned key, so releasing Alt doesn't open the app's menu bar. That's the same trick AutoHotkey uses. Kemper then waits until you let go of the modifier keys and types the text with [`SendInput`](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-sendinput) in Unicode mode, which doesn't depend on the keyboard layout. Characters outside the basic plane, such as emoji, are sent as UTF-16 surrogate pairs.
- **Window.** The interface is HTML/CSS/JS kept inside `kemper.pyw` and shown with pywebview, which uses Edge WebView2. The page calls into Python through pywebview's JS bridge, and the title bar follows dark mode through DWM.
- **One instance, and CLI control.** The running Kemper listens on `127.0.0.1:47321` for a few short commands: `show`, `quit`, `reload`, `ping`, and `keypack` followed by a file path. That's how a second launch shows the window, how double-clicking a keypack reaches a running Kemper, and how CLI changes reach it. It only accepts connections from your own PC.
- **Keypacks.** The Keypack Editor is a third window that uses the main window's styles. Keypack files are validated in Python, as untrusted input, before anything is shown, and conflicts are worked out in Python too, so the window and the files follow the same rules.
- **Icon.** Kemper's icon is stored inside `kemper.pyw` as PNG data. At startup it's written to `%APPDATA%\Kemper\kemper.ico`, because the window title bar and the desktop shortcut need a real file. Kemper also gives itself its own taskbar identity (an AppUserModelID), so the taskbar shows its icon instead of Python's.
- **Quick picker.** A second, borderless window that's created hidden and registered under its own hotkey. When the combo fires, Kemper remembers which window had focus, puts the panel by the mouse and shows it. When you pick, Kemper hides the panel, gives focus back to that window and types the text there, the same way as a normal shortcut.
- **Settings** are validated on the Python side before saving, whatever the UI or CLI sent.

### On macOS and Linux

- **Keys are stored the same way everywhere,** as Windows virtual-key codes. Tables inside `kemper.pyw` translate them to macOS key codes and X11 keysyms.
- **macOS:**
  - Hotkeys come from a Quartz event tap, created through pynput. Kemper checks each key press there and drops its own combos, so the app in front never sees them.
  - Typing uses Quartz Unicode key events.
  - This is why macOS asks for Input Monitoring and Accessibility.
- **Linux:**
  - Hotkeys are X11 key grabs on the root window, so the combos go to Kemper and not the app in front. They're grabbed with every Caps Lock and Num Lock state so those don't matter.
  - Typing uses the X11 test extension through python-xlib, the same way `xdotool` works: a character missing from the keyboard layout gets a spare key code mapped to it for a moment.
  - Wayland sessions don't allow global key grabs at all, which is why Kemper needs Xorg.
- **Start at sign-in, the desktop shortcut and `.kmppck` files** use each system's standard places: LaunchAgents on macOS, and XDG autostart, `.desktop` files and the shared MIME database on Linux.

## Troubleshooting

Start with `python kemper.pyw --doctor`. It catches most problems and prints the fix.

| Problem | Fix |
|---|---|
| A combo does nothing | Is Kemper running and active? Check with `--status`. Another app may own the combo; `--doctor` lists those. |
| Red notice: *"Already used by another app"* | Pick different keys for the shortcuts it names. |
| The window doesn't open | Run `python kemper.pyw` from a terminal to see the error. Usually pywebview or WebView2 is missing (`--doctor`). |
| *"Kemper is already running"* with `--cli` | Stop the window version with `--quit`, then start `--cli`. |
| Kemper doesn't start at sign-in | Switch **Start with Windows** / **Start at login** off and on again (or run `--autostart on`). The startup entry may point to an old location of the file. |
| macOS: shortcuts do nothing | Allow Kemper's app (Terminal, or Python) under System Settings → Privacy & Security → **Accessibility** and **Input Monitoring**, then restart Kemper. `--doctor` checks Accessibility. |
| Linux: shortcuts do nothing | You're probably in a Wayland session. Log out, choose **"Ubuntu on Xorg"** with the gear on the login screen, and log in again. `--doctor` tells you which session you're in. |
| Linux: Copy instructions doesn't copy | Install a clipboard tool: `sudo apt install xclip`. |
| The quick picker doesn't open | It needs the window version of Kemper, not `--cli`. Check that it's switched on and that its combo isn't red or taken (`--doctor`). |
| Double-clicking a `.kmppck` doesn't open Kemper | Open Kemper's window once; it links the file type. If Windows asks which app to use, pick Kemper's. `--doctor` shows whether the link is in place. |
| *"This keypack was made by a newer Kemper"* | Update `kemper.pyw` from the [releases page](https://github.com/Shashwat-Gupta57/Kemper/releases). |
| Text appears in the wrong app | Kemper types into whichever window has focus when you press the combo. |
| A combo works everywhere except one app | Apps running as administrator ignore input from normal apps. That's a Windows rule. Run Kemper as administrator too, if you need it there. |
| Port 47321 is used by another program | Change `PORT` near the top of `kemper.pyw`. |
| Ctrl+Shift+0 (or another Ctrl+Shift+digit) never fires on Windows | Windows swallows it for switching keyboard language. See below. |

### Ctrl+Shift+0 (or another combo) never fires

On Windows, the text-input system can reserve combos to switch straight to a keyboard layout. It catches them before any app sees them, so Kemper can register the combo but never receives it, and the key box in the window doesn't react when you press it. Kemper names these combos in its red "won't work" notice and in `--doctor`.

The usual culprit is **Ctrl+Shift+0**. Windows ships it as "switch to the Japanese input method", and the hotkey stays active even on PCs without Japanese. That's also why Ctrl+Shift+0 does nothing in Excel and other apps.

To free it:
- **If the language is installed:** in Settings → Time & language → Typing → Advanced keyboard settings → **Input language hot keys**, pick the entry, choose **Change Key Sequence** and set it to *Not assigned*.
- **If the entry isn't listed** (the Japanese one usually isn't): clear it in the registry from PowerShell. `00000104` is the Ctrl+Shift+0 entry; `--doctor` and the registry key list others.

  ```powershell
  $k = "HKCU:\Control Panel\Input Method\Hot Keys\00000104"
  Set-ItemProperty $k "Virtual Key" ([byte[]](0xFF, 0, 0, 0))
  Set-ItemProperty $k "Key Modifiers" ([byte[]](0, 0xC0, 0, 0))
  Set-ItemProperty $k "Target IME" ([byte[]](0, 0, 0, 0))
  ```

  Then sign out and back in. This only affects your account, and you can undo it by setting the values back. Otherwise, pick a different combo, like Ctrl+Alt+0.

## Limits

- Linux needs an X11 (Xorg) session; Wayland doesn't allow global hotkeys.
- On macOS there's no desktop shortcut and no double-click for `.kmppck` files (use **Import a keypack…**).
- On Windows, shortcuts can't type into apps running as administrator unless Kemper runs as administrator too.
- Combos already owned by the system or another app can't be used.
- There's no tray icon. Run `kemper.pyw` or `--show` to open the window.
- The quick picker and keypacks need the window version; they're off in `--cli` mode.
- The window's text field is single-line. Multi-line text works through the settings file.
- Changing settings from the CLI while the window has unsaved edits replaces those edits with the saved settings.

## Development

```powershell
git clone https://github.com/Shashwat-Gupta57/Kemper.git
cd Kemper
python -m pip install -r requirements.txt
python test_kemper.py
```

`test_kemper.py` checks:
- conflict detection, save validation and combo parsing
- Unicode encoding
- the CLI, run end to end against a throwaway settings folder

It needs no GUI or display, and CI runs it on Windows, macOS and Linux on every push. See [CONTRIBUTING.md](../CONTRIBUTING.md).

Code layout inside `kemper.pyw`, top to bottom:
- Win32 input: hotkeys and typing
- the settings model and validation
- startup
- the engine shared by the window and `--cli`
- the single-instance channel
- combo parsing
- the CLI commands
- the window launcher
- the embedded quick picker page (`PICKER_HTML`)
- the embedded page (`UI_HTML`)
