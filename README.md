# Kemper

**Kemper** (short for **Key Mapper**) types a character or a piece of text when you press a key combo, in any app on Windows.

Press **Alt + 2** and get **²**. Press **Alt + Shift + 2** and get **₂**. Press **Ctrl + Alt + E** and get **€**. You choose the combos and the text.

<p align="center">
  <img src="docs/images/light.png" alt="Kemper in light mode, showing six shortcuts such as Alt + 2 typing ²" width="380">
  <img src="docs/images/dark.png" alt="Kemper in dark mode with the same shortcuts" width="380">
</p>

[![tests](https://github.com/Shashwat-Gupta57/Kemper/actions/workflows/tests.yml/badge.svg)](https://github.com/Shashwat-Gupta57/Kemper/actions/workflows/tests.yml)
![Windows 10 and 11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB)
[![MIT License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Features

- **Works in every app.** Word, Chrome, Discord, VS Code, Notepad, anything you can type into.
- **Set a combo like in a game.** Click the key box, press the keys, and you're done.
- **Any text.** One character, an emoji, a symbol, or a whole phrase.
- **Catches clashes.** If two shortcuts use the same keys, both turn red and Kemper won't save until you fix them.
- **Light and dark mode.** Follows Windows, or pick one yourself.
- **Starts with Windows** and runs quietly in the background. Closing the window doesn't stop it.
- **Deactivate** turns every shortcut off without quitting.
- **Full command line.** Run it with no window, and add, remove, list and check shortcuts from a terminal.
- **One file.** The whole program is [`kemper.pyw`](kemper.pyw). Its only dependency is pywebview, for the window.

## Install

You need **Windows 10 or 11** and **[Python 3.10 or newer](https://www.python.org/downloads/)**.

1. Download [`kemper.pyw`](kemper.pyw) and put it in a folder where it can stay, for example `C:\Tools\Kemper\`.
2. Open a terminal in that folder and run:

   ```powershell
   python -m pip install pywebview
   python kemper.pyw --install
   ```

`--install` makes Kemper start with Windows and opens its window. That's it.

> If you only want the command line, `pywebview` is optional. Skip it and use `--cli`.

## Use it

### In the window

1. Click **Add Shortcut**. The key box turns blue and says *Press keys…*
2. Press your combo, for example **Alt + 2**. Esc cancels.
3. Type or paste the text it should produce, for example `²`.
4. Click **Save** (or press **Ctrl + S**).

Now press Alt + 2 in any app and ² appears.

| Recording a combo | Two shortcuts with the same keys |
|---|---|
| <img src="docs/images/recording.png" alt="A key box glowing blue with the words Press keys" width="360"> | <img src="docs/images/conflict.png" alt="Two rows marked red because both use Alt + 2, with Save disabled" width="360"> |

Closing the window only hides it; your shortcuts keep working. Run `kemper.pyw` again to bring the window back. **Quit** stops Kemper. **Deactivate** turns shortcuts off but leaves Kemper running.

<img src="docs/images/deactivated.png" alt="Kemper deactivated: the shortcut list is dimmed and the button reads Activate" width="380">

### From the command line

Everything the window does also works from a terminal:

```console
> python kemper.pyw --add "Alt+2" "²"
Added Alt + 2  →  ²

> python kemper.pyw --add "Alt+Shift+2" "₂"
Added Alt + Shift + 2  →  ₂

> python kemper.pyw --keys
  Alt + 2          →  ²
  Alt + Shift + 2  →  ₂

2 shortcut(s), active.

> python kemper.pyw --add "alt+2" "x"
kemper: Alt + 2 already types ². Remove it first:  python kemper.pyw --remove "alt+2"
```

Run Kemper with no window at all. Every shortcut you use is logged as it happens:

```console
> python kemper.pyw --cli
Kemper 1.0.0 is running in this terminal (no window).
  2 shortcut(s) active. Each one shows up here when you use it.
  Press Ctrl+C to stop.

  13:19:58  Alt + 2  →  ²
  13:20:04  Alt + Shift + 2  →  ₂
```

Something not working? `--doctor` checks everything and tells you how to fix each problem:

```console
> python kemper.pyw --doctor
Kemper 1.0.0 doctor

  ✓  Python 3.12.10
  ✓  pywebview 6.2.1 is installed (needed for the window)
  ✓  Edge WebView2 158.0.4370.33 (draws the window)
  ✓  2 shortcut(s) saved in C:\Users\you\AppData\Roaming\Kemper\mappings.json
  ✓  Shortcuts are active
  ✓  Kemper is running
  ✓  Starts with Windows
  ✓  Skipped the hotkey check because the running Kemper is holding them

All good.
```

All commands:

| Command | What it does |
|---|---|
| *(none)* | Open the window |
| `--cli` | Run in the terminal with no window. Ctrl+C stops it |
| `--keys` | List your shortcuts |
| `--add COMBO TEXT` | Add a shortcut |
| `--remove COMBO` | Remove a shortcut |
| `--activate` / `--deactivate` | Turn all shortcuts on or off |
| `--status` | Is Kemper running? Where are its files? |
| `--doctor` | Find problems and say how to fix them |
| `--show` | Open the window of the running Kemper |
| `--quit` | Stop the running Kemper |
| `--install` | Start Kemper with Windows, and start it now |
| `--uninstall` | Remove Kemper from this PC |
| `--help`, `--version` | Help, version |

## Ideas for shortcuts

| Combo | Types | Handy for |
|---|---|---|
| Alt + 2 / Alt + Shift + 2 | ² / ₂ | Math, chemistry (H₂O, x²) |
| Alt + 0 | ° | Temperatures, angles |
| Ctrl + Alt + E | € | Prices |
| Ctrl + Alt + Right | → | Notes, arrows |
| Ctrl + Shift + - | — | Em dash in writing |
| Ctrl + Alt + S | `¯\_(ツ)_/¯` | Chat |

## Uninstall

```powershell
python kemper.pyw --uninstall
```

This asks you to confirm, then stops Kemper, removes it from Windows startup, deletes your shortcuts and settings, and deletes `kemper.pyw` itself. It changes nothing else on your PC. Add `--yes` to skip the question.

## Documentation

The [full documentation](docs/DOCUMENTATION.md) covers every command, the combo syntax, the settings file, how Kemper works inside, troubleshooting and limits.

## Contributing

Bug reports and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 Shashwat Gupta
