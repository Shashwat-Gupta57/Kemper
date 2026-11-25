# Kemper documentation

Kemper (Key Mapper) types a character or text when you press a key combo, in any Windows app. This page covers everything in detail. For a quick start, see the [README](../README.md).

- [Requirements](#requirements)
- [Installing](#installing)
- [The window](#the-window)
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

| | Needed for | Notes |
|---|---|---|
| Windows 10 or 11 | everything | Kemper uses Windows' own hotkey and typing functions |
| Python 3.10+ | everything | [python.org](https://www.python.org/downloads/). Tick *Add python.exe to PATH* when installing |
| [pywebview](https://pywebview.flowrl.com/) | the window | `python -m pip install pywebview`. Not needed for the CLI |
| Edge WebView2 Runtime | the window | Built into Windows 11 and current Windows 10. [Download](https://go.microsoft.com/fwlink/p/?LinkId=2124703) if `--doctor` says it's missing |

## Installing

Kemper is a single file, `kemper.pyw`. Keep it in a folder where it can stay, because Windows startup points at that exact path.

```powershell
python -m pip install pywebview
python kemper.pyw --install
```

`--install` adds Kemper to Windows startup and opens it. If you move `kemper.pyw` later, run `--install` again from the new place. `--doctor` warns you if the startup entry points to an old location.

## The window

Open it by running `kemper.pyw` (double-click works), or with `python kemper.pyw --show`.

| Part | What it does |
|---|---|
| **Deactivate / Activate** | Turns every shortcut off or back on. Kemper stays running, and the choice is remembered after a restart |
| **Quit** | Stops Kemper completely. Shortcuts stop working until you start it again |
| **Start with Windows** | Adds or removes Kemper from Windows startup |
| **Appearance** | System follows your Windows light or dark setting as it changes. Light and Dark force one look |
| **Key box** | Click it, then press a combo. Esc or clicking elsewhere cancels |
| **Text field** | What the combo types. Paste anything, including emoji |
| **Red minus** | Deletes that shortcut |
| **Add Shortcut** | Adds a row and starts recording its combo right away |
| **Save** (Ctrl + S) | Saves and applies your changes. It's only enabled when there's something valid to save |

**Conflicts.** When two shortcuts use the same keys, both rows turn red and Save stays disabled until you change one of them. Modifier order doesn't matter: Alt + Shift + 2 and Shift + Alt + 2 are the same combo.

**Closing the window** only hides it. Shortcuts keep working. Running `kemper.pyw` again brings the window back instead of starting a second copy.

While you record a combo, Kemper pauses all shortcuts, so pressing an existing combo records it instead of typing its text.

## Command line reference

Run commands with `python kemper.pyw <command>`. Use `python`, not `pythonw`: `pythonw` has no console, so you wouldn't see any output.

Commands that change settings (`--add`, `--remove`, `--activate`, `--deactivate`) also update a running Kemper immediately, whether it's the window or `--cli`.

### `--cli`

Runs Kemper in the terminal with no window. It logs each shortcut as you use it and reloads whenever you change settings from another terminal. Stop it with Ctrl+C, or `--quit` from another terminal.

```console
> python kemper.pyw --cli
Kemper 1.0.0 is running in this terminal (no window).
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

### `--activate`, `--deactivate`

Turns all shortcuts on or off without quitting Kemper. This is the same as the button in the window.

### `--status`

```console
> python kemper.pyw --status
Kemper 1.0.0
  Running:             yes
  Shortcuts:           2 (active)
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

### `--install`, `--uninstall`

See [Installing](#installing) and [Uninstalling](#uninstalling).

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

**Combos Windows keeps for itself.** Some combos are already owned by Windows or another app, for example many `Win + …` combos, `Ctrl + Alt + Delete` and `Alt + Tab`. Kemper can't take those. The window shows a red notice naming them, and `--doctor` lists them.

## What text can be typed

Anything Unicode: accented letters, symbols, math (², ₂, ∑, √), arrows, emoji (😀), other scripts, and whole sentences. Kemper types it as text, so it works no matter which keyboard layout you use.

A line break in the text presses Enter. The window's text field is single-line, so add multi-line text by editing the [settings file](#settings-file) and writing `\n` in the JSON string.

## Settings file

Kemper keeps its settings in `%APPDATA%\Kemper\mappings.json` (usually `C:\Users\<you>\AppData\Roaming\Kemper\mappings.json`):

```json
{
  "mappings": [
    { "mods": ["Alt"], "vk": 50, "key": "2", "text": "²" },
    { "mods": ["Alt", "Shift"], "vk": 50, "key": "2", "text": "₂" }
  ],
  "appearance": "system",
  "active": true
}
```

| Field | Meaning |
|---|---|
| `mods` | Any of `Ctrl`, `Alt`, `Shift`, `Win` |
| `vk` | The Windows [virtual-key code](https://learn.microsoft.com/windows/win32/inputdev/virtual-key-codes) of the key (50 is `2`) |
| `key` | The key's name, shown in the window |
| `text` | What gets typed |
| `appearance` | `system`, `light` or `dark` |
| `active` | `false` when Kemper is deactivated |

You can edit the file by hand. Afterwards, restart Kemper, or run any setting command so a running Kemper reloads it. Run `--doctor` to check your edit. Kemper never saves a file with conflicts or empty entries, and it saves atomically, so a crash can't leave a half-written file.

## Running in the background and at startup

- Closing the window hides it. Kemper keeps running until you click **Quit** or run `--quit`.
- **Start with Windows** adds an entry under `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` named `Kemper`. It runs `pythonw.exe "<path>\kemper.pyw" --hidden`. No admin rights are needed, and only your user account is affected.
- Only one Kemper runs at a time. A second launch tells the first one to show its window, then exits.

Why not a Windows *service*? Services run in an isolated session that can't see your keyboard or type into your apps, so a hotkey tool can't be one. Starting at login is the standard way to do it.

## Uninstalling

```powershell
python kemper.pyw --uninstall
```

After you confirm, Kemper:
1. stops the running Kemper,
2. removes its Windows startup entry,
3. deletes `%APPDATA%\Kemper` (your shortcuts and settings),
4. deletes `kemper.pyw` itself.

It touches nothing else. pywebview stays installed because other programs may use it; remove it with `python -m pip uninstall pywebview` if you like. Add `--yes` to skip the confirmation.

## How Kemper works

Kemper is one Python file with no dependencies beyond the standard library and pywebview.

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
- **One instance, and CLI control.** The running Kemper listens on `127.0.0.1:47321` for a few one-word commands: `show`, `quit`, `reload`, `ping`. That's how a second launch shows the window and how CLI changes reach a running Kemper. It only accepts connections from your own PC.
- **Settings** are validated on the Python side before saving, whatever the UI or CLI sent.

## Troubleshooting

Start with `python kemper.pyw --doctor`. It catches most problems and prints the fix.

| Problem | Fix |
|---|---|
| A combo does nothing | Is Kemper running and active? Check with `--status`. Another app may own the combo; `--doctor` lists those. |
| Red notice: *"Already used by another app"* | Pick different keys for the shortcuts it names. |
| The window doesn't open | Run `python kemper.pyw` from a terminal to see the error. Usually pywebview or WebView2 is missing (`--doctor`). |
| *"Kemper is already running"* with `--cli` | Stop the window version with `--quit`, then start `--cli`. |
| Kemper doesn't start at login | Run `--install` again. The startup entry may point to an old location of the file. |
| Text appears in the wrong app | Kemper types into whichever window has focus when you press the combo. |
| A combo works everywhere except one app | Apps running as administrator ignore input from normal apps. That's a Windows rule. Run Kemper as administrator too, if you need it there. |
| Port 47321 is used by another program | Change `PORT` near the top of `kemper.pyw`. |

## Limits

- Windows only.
- Shortcuts can't type into apps running as administrator unless Kemper runs as administrator too.
- Combos already owned by Windows or another app can't be used.
- There's no tray icon. Run `kemper.pyw` or `--show` to open the window.
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

It runs on Windows with no GUI, and CI runs it on every push. See [CONTRIBUTING.md](../CONTRIBUTING.md).

Code layout inside `kemper.pyw`, top to bottom:
- Win32 input: hotkeys and typing
- the settings model and validation
- startup
- the engine shared by the window and `--cli`
- the single-instance channel
- combo parsing
- the CLI commands
- the window launcher
- the embedded page (`UI_HTML`)
