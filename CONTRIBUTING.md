# Contributing to Kemper

Thanks for helping. Kemper is small on purpose, so please keep changes small and focused too.

## Reporting a bug

[Open an issue](https://github.com/Shashwat-Gupta57/Kemper/issues/new/choose) and include:
- the output of `python kemper.pyw --doctor`
- your system (Windows, macOS or Linux, and its version) and keyboard layout
- the combo and text involved, what you expected, and what happened

## Making a change

1. Fork the repo and create a branch.
2. Make your change in `kemper.pyw`. Kemper is a single file on purpose; please keep it that way.
3. Add or update a check in `test_kemper.py` for any new logic.
4. Run the tests (on any system):

   ```powershell
   python -m pip install -r requirements.txt
   python test_kemper.py
   ```

5. If you changed the window, test it by hand in both light and dark mode, and include a screenshot in the pull request.
6. Add a line under a new *Unreleased* heading in [CHANGELOG.md](CHANGELOG.md).
7. Open a pull request that explains what changed and why.

## Adding a keypack to the Marketplace

The [Marketplace](marketplace) is a folder of `.kmppck` files. To add yours:

1. Make the keypack in Kemper's Keypack Editor, or by hand, or with an AI chat (see [docs/AI_INSTRUCTIONS.md](docs/AI_INSTRUCTIONS.md)). Write every combo in the readable form: `{"keys": "Ctrl+Alt+E", "text": "€"}`.
2. Add a `"description"`: one short sentence about what the keypack is for.
3. Save it in `marketplace/` with a short lowercase file name with dashes, like `music-symbols.kmppck`.
4. Add a row for it to the table in [marketplace/README.md](marketplace/README.md).
5. Run `python test_kemper.py`. Every Marketplace keypack must:
   - load in Kemper without errors
   - use Ctrl or Alt in every combo, and leave Ctrl + C, V, S and the other everyday shortcuts alone
   - stay off the quick picker's combo (Ctrl + Alt + K) and off Ctrl + Shift + digits, which Windows keeps for itself
   - share no combo with any other Marketplace keypack, so people can import all of them
6. Open a pull request. The website picks up the new keypack as soon as it's merged.

A good keypack is easy to remember: use the first letter or a key that looks like the output, Shift for a variant, and the arrow keys for arrows.

## Guidelines

- Standard library first. A new dependency needs a strong reason.
- Never save an invalid settings file. Validation lives in `clean_mappings`.
- Keep user-facing messages plain and specific, and say how to fix the problem.
- Kemper runs on Windows, macOS and Linux (X11). Anything that touches the operating system goes in the per-system blocks near the top of `kemper.pyw`, with the same function names for every system.

## Code of conduct

Be kind and assume good intent. Harassment of any kind isn't welcome here.
