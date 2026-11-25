# Security

## What Kemper can and can't do

Kemper registers the specific key combos you configure and types text when they're pressed. It does **not** log keystrokes, read what you type, or send anything over the internet.

- It only sees the combos you set up. Windows delivers those, and nothing else, to Kemper.
- It listens on `127.0.0.1:47321`, which other computers can't reach, for the commands `show`, `quit`, `reload`, `ping` and `keypack <file>`. Any program on your own PC could send these. The worst a local program can do through them is show, reload or stop Kemper, or open an import question that you still have to accept.

## Keypacks from other people

A keypack (`.kmppck`) is only data: shortcuts and their text. It can't run code. Kemper:
- validates every keypack before showing it, and refuses oversized or malformed files,
- never imports anything without asking you first,
- shows every shortcut in the keypack, and marks the ones that clash with yours or take over common keys like Ctrl + C,
- doesn't save imported shortcuts until you click Save.

Still, only import keypacks you trust. A shortcut can type any text into whatever app is focused.
- Settings are plain JSON in `%APPDATA%\Kemper`. Don't store passwords as shortcut text: anyone with access to your user account can read that file.

## Reporting a vulnerability

Please don't open a public issue for security problems. Use GitHub's [private vulnerability reporting](https://github.com/Shashwat-Gupta57/Kemper/security/advisories/new) instead. Expect a reply within a week.
