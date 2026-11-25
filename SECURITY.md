# Security

## What Kemper can and can't do

Kemper registers the specific key combos you configure and types text when they're pressed. It does **not** log keystrokes, read what you type, or send anything over the internet.

- It only sees the combos you set up. Windows delivers those, and nothing else, to Kemper.
- It listens on `127.0.0.1:47321`, which other computers can't reach, for the one-word commands `show`, `quit`, `reload` and `ping`. Any program on your own PC could send these. The worst a local program can do through them is show, reload or stop Kemper.
- Settings are plain JSON in `%APPDATA%\Kemper`. Don't store passwords as shortcut text: anyone with access to your user account can read that file.

## Reporting a vulnerability

Please don't open a public issue for security problems. Use GitHub's [private vulnerability reporting](https://github.com/Shashwat-Gupta57/Kemper/security/advisories/new) instead. Expect a reply within a week.
