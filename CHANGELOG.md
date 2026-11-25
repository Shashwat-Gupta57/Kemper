# Changelog

All notable changes to Kemper are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-11-25

First public release. Kemper is rebuilt around a new window, a full command line and the quick picker.

### Added
- A new window with an iOS-style look and smooth rendering, light and dark mode (follows Windows or set by hand), and a dark title bar.
- Kemper's own icon in the window, the taskbar and an optional desktop shortcut (switch in the window, or `--desktop on|off`).
- Quick picker: a combo (Ctrl + Alt + K by default) pops up all your shortcuts by the mouse, like Win + V does for the clipboard.
  - Search, then pick with Enter or a click.
  - Drag it by its top strip.
  - Set it up in its own section of the window or with `--picker`.
- Deactivate / Activate, which turns all shortcuts off without quitting and is remembered after a restart.
- Command line:
  - `--cli` runs Kemper with no window and logs shortcuts as you use them.
  - Commands: `--keys`, `--add`, `--remove`, `--picker`, `--activate`, `--deactivate`, `--autostart`, `--desktop`, `--status`, `--doctor`, `--show`, `--quit`, `--uninstall`, `--help`, `--version`.
  - Changes reach a running Kemper immediately.
- `--uninstall` removes Kemper from startup and the desktop, deletes its settings, and deletes the program file.
- If pywebview is missing, starting with Windows still runs your shortcuts, just without a window.

### Changed
- Conflicts are now also blocked when saving, from the window, the CLI or a hand-edited settings file, and the quick picker's combo counts too.
- Settings moved to `{ "mappings": [...], ... }`. 1.x settings files are read automatically.
- Kemper is still a single file: everything, including the window's pages and the icon, lives in `kemper.pyw`.

### Fixed
- Key boxes no longer overflow and hide the text field while recording.
- The Save button is no longer cut off on scaled displays.

## [1.0.0] - 2026-11-25

- First version: map key combos to text in a tkinter window, with conflicts marked in red and start with Windows.

[2.0.0]: https://github.com/Shashwat-Gupta57/Kemper/releases/tag/v2.0.0
[1.0.0]: https://github.com/Shashwat-Gupta57/Kemper/commit/89c2d7b
