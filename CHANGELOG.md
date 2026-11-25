# Changelog

All notable changes to Kemper are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-25

First public release.

### Added
- Map key combos to any Unicode text, typed into whichever app has focus.
- Window with an iOS-style look, light and dark mode (follows Windows or set by hand), and a dark title bar.
- Game-style combo recording: click the key box, press the keys.
- Conflict detection: clashing shortcuts turn red, and saving is blocked in the window, the CLI and the settings validator.
- Deactivate / Activate, which turns all shortcuts off without quitting and is remembered after a restart.
- Start with Windows, with no admin rights.
- Command line: `--cli` (runs with no window and logs shortcuts as you use them), `--keys`, `--add`, `--remove`, `--activate`, `--deactivate`, `--status`, `--doctor`, `--show`, `--quit`, `--install`, `--uninstall`, `--help`, `--version`.
- CLI changes reach a running Kemper immediately.
- `--uninstall` removes Kemper from startup, deletes its settings and deletes the program file.
- Single-file program: everything, including the window's page, lives in `kemper.pyw`.

[1.0.0]: https://github.com/Shashwat-Gupta57/Kemper/releases/tag/v1.0.0
