# Contributing to Kemper

Thanks for helping. Kemper is small on purpose, so please keep changes small and focused too.

## Reporting a bug

[Open an issue](https://github.com/Shashwat-Gupta57/Kemper/issues/new/choose) and include:
- the output of `python kemper.pyw --doctor`
- your Windows version and keyboard layout
- the combo and text involved, what you expected, and what happened

## Making a change

1. Fork the repo and create a branch.
2. Make your change in `kemper.pyw`. Kemper is a single file on purpose; please keep it that way.
3. Add or update a check in `test_kemper.py` for any new logic.
4. Run the tests on Windows:

   ```powershell
   python -m pip install -r requirements.txt
   python test_kemper.py
   ```

5. If you changed the window, test it by hand in both light and dark mode, and include a screenshot in the pull request.
6. Add a line under a new *Unreleased* heading in [CHANGELOG.md](CHANGELOG.md).
7. Open a pull request that explains what changed and why.

## Guidelines

- Standard library first. A new dependency needs a strong reason.
- Never save an invalid settings file. Validation lives in `clean_mappings`.
- Keep user-facing messages plain and specific, and say how to fix the problem.
- Windows only: Kemper relies on Win32 APIs by design.

## Code of conduct

Be kind and assume good intent. Harassment of any kind isn't welcome here.
