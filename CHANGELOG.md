# Changelog

All notable changes to Kemper are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## [3.1.1] - 2026-11-25

### Fixed
- **Ctrl+Shift+0 silently doing nothing on Windows.** Windows reserves it, even without Japanese installed, as "switch to the Japanese input method", and its text-input system swallows the keys before any app sees them. Kemper now reads Windows' keyboard-layout switch hotkeys. It names any shortcut or quick-picker combo they block in its red "won't work" notice and in `--doctor`, even while Kemper is running. The documentation explains how to free the combo.

## [3.1.0] - 2026-11-25

Kemper runs on macOS and Linux too.

### Added
- **macOS:**
  - Hotkeys through a Quartz event tap, via pynput. The app in front never sees Kemper's combos.
  - Unicode typing.
  - Start at login with a LaunchAgent.
  - The window shows Cmd and Option.
- **Linux (X11):**
  - Hotkeys through X11 key grabs, and Unicode typing through the X11 test extension, with python-xlib only (pure Python, nothing to compile).
  - Start at login, a desktop and app-menu launcher with Kemper's icon, and double-click for `.kmppck` keypacks through the shared MIME database.
  - The window shows Super.
- Settings and keypacks are identical on every system. `Cmd`, `Option` and `Super` are accepted when typing combos.
- `--doctor` checks each system's needs: macOS Accessibility, X11 versus Wayland, and a clipboard tool on Linux. `--status` shows the system.
- Settings live in each system's usual folder, or in `KEMPER_HOME` if it's set.
- CI runs the tests on Windows, macOS and Ubuntu.

### Changed
- All Windows code sits in one block, unchanged, behind the same functions as the macOS and Linux versions.
- The quick picker opens by the mouse and stays on screen on every system.
- The window names startup per system: "Start with Windows" on Windows, "Start at login" elsewhere.

### Fixed
- The website's screenshots keep their real proportions on every screen size.

## [3.0.1] - 2026-11-25

### Added
- Kemper's website, [kemper.talken.in](https://kemper.talken.in). It's built from `web/` and published to GitHub Pages on every push. Its screenshots and AI instructions come straight from `docs/`, so they always match the app.

### Removed
- An unused screenshot.

## [3.0.0] - 2026-11-25

Keypacks: shareable sets of shortcuts.

### Added
- **Keypacks** (`.kmppck` files): a set of shortcuts with a name stored inside the file, so the file name can differ.
- **Importing:** double-click a keypack, use **Keypacks → Import a keypack…**, or run `--keypack FILE`. Kemper shows every shortcut in it before you decide:
  - Red: clashes with your shortcuts, your quick picker, or the keypack itself.
  - Orange: takes over common keys like Ctrl + C.
  - Gray: already in your Kemper, so it's skipped.

  Conflicts don't block the import, only saving, until you fix them.
- **Keypack Editor**, opened from **Keypacks → Create a keypack** with **New keypack** or **Edit a keypack file…**:
  - Import from your Kemper through a gallery with Select all / Deselect all.
  - Add, Remove, and Undo / Redo for the last 50 changes, with Ctrl + Z, Ctrl + Y, Ctrl + N, Delete and Ctrl + S.
  - Export with a keypack name, file name and folder. It asks before replacing a file, and asks before closing with changes you haven't exported.
- **Keypacks made by AI:**
  - **✦ AI** in the Keypack Editor, or **Create a keypack → Make one with AI…**, gives you instructions to copy into any AI chat.
  - You describe the shortcuts you want, then paste the AI's answer back. Chat text around the JSON is ignored.
  - The instructions are also in `docs/AI_INSTRUCTIONS.md` and printed by `--ai-instructions`.
- Keypacks use a readable form, `{"keys": "Ctrl+Alt+E", "text": "€"}`, that people and AI can write by hand. Kemper writes it too, falling back to the exact form only for keys without a readable name.
- Kemper links the `.kmppck` file type to itself, with its icon, for the current user (no admin), and fixes the link if Kemper moves. `--doctor` checks it, and `--uninstall` removes it.
- A running Kemper now accepts a keypack handed over by a second launch and comes to the front to ask about it.

### Changed
- Keypack files are treated as untrusted:
  - They're capped at 1 MB and 1,000 shortcuts.
  - Every shortcut is validated.
  - A shortcut's text is limited to 10,000 characters, here and in your own settings.

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

[3.1.1]: https://github.com/Shashwat-Gupta57/Kemper/releases/tag/v3.1.1
[3.1.0]: https://github.com/Shashwat-Gupta57/Kemper/releases/tag/v3.1.0
[3.0.1]: https://github.com/Shashwat-Gupta57/Kemper/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/Shashwat-Gupta57/Kemper/releases/tag/v3.0.0
[2.0.0]: https://github.com/Shashwat-Gupta57/Kemper/releases/tag/v2.0.0
[1.0.0]: https://github.com/Shashwat-Gupta57/Kemper/commit/89c2d7b
