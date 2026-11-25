# Make keypacks with AI

Any AI chat (ChatGPT, Claude, Gemini, Copilot, …) can write a [Kemper](../README.md) keypack for you. Describe the shortcuts you want in plain words, and the AI writes the file.

1. **Copy the instructions below.** Use the copy button in the top-right corner of the box. They're also in Kemper: **Keypack Editor → ✦ AI → Copy instructions**, or run `python kemper.pyw --ai-instructions`.
2. **Paste them into a new AI chat, then say what you want.** For example:
   - *"Greek letters for math, with capitals on Shift."*
   - *"Arrows → ← ↑ ↓ on Ctrl+Alt with the arrow keys, plus ⇒ and ⇔."*
   - *"My email signature on Ctrl+Alt+S, and my address on Ctrl+Alt+A."*
   - *"Chemistry: subscript digits on Alt+Shift+0 to 9, superscript digits on Alt+0 to 9."*
3. **Bring the answer into Kemper,** in either of two ways:
   - **Paste it:** in the Keypack Editor click **✦ AI**, paste the AI's whole answer into step 3 and click **Add to keypack**. Check the shortcuts, then **Export**, or import them into your own Kemper.
   - **Save it as a file:** copy the JSON into Notepad, save it as `something.kmppck` with *Save as type: All files*, and double-click it. Kemper shows every shortcut and any conflicts before importing.

Kemper validates everything the AI writes. Broken shortcuts are refused with a message saying which one is wrong, and clashing ones are marked red before you import anything.

## The instructions

````text
# Instructions: create a Kemper keypack

You are helping someone make a keypack for Kemper, an app for Windows, macOS and Linux that types a character or some text whenever a key combination is pressed (for example, Alt+2 types ²). A keypack is a JSON file with the extension .kmppck that holds a named set of these shortcuts. After these instructions, the person will tell you what they want; build the keypack from that.

## Your reply

1. Put the complete keypack in a single ```json code block. Inside the block, write only the JSON, with no comments.
2. Below the block, add a short table of the combos and what each one types, so the person knows which keys to press.
3. If the request is too vague to choose good shortcuts, ask one short question first. Otherwise, make sensible choices yourself.

## The format

```json
{
  "format": "kemper-keypack",
  "version": 1,
  "name": "Short descriptive name",
  "mappings": [
    { "keys": "Alt+2", "text": "²" }
  ]
}
```

- "format" must be exactly "kemper-keypack", and "version" must be 1.
- "name" is what people see when they import the keypack: 1 to 100 characters.
- "mappings" is the list of shortcuts, from 1 to 1000 of them. Each one has exactly two fields, "keys" and "text".

## "keys": the key combination

- Write it as modifiers plus one key, joined with +, for example "Ctrl+Alt+E" or "Alt+Shift+2".
- Modifiers: Ctrl, Alt, Shift, Win.
- Keys:
  - letters A-Z and digits 0-9
  - F1-F24
  - Num0-Num9 (number pad)
  - Space, Enter, Tab, Esc, Backspace, Delete, Insert, Home, End, PageUp, PageDown, Left, Right, Up, Down
  - the punctuation keys - = [ ] ; ' , . / ` \
- Name the physical key on a US keyboard. A character that needs Shift is written as Shift plus its key: "Shift+1", never "!".
- Every mapping must use a different combination. Modifier order doesn't matter: "Alt+Shift+2" and "Shift+Alt+2" are the same combination.
- Always include Ctrl or Alt. Shift alone, or no modifier at all, would replace normal typing.
- Don't use combinations that Windows or most apps already need:
  - Ctrl+A, C, F, N, O, P, S, T, V, W, X, Y and Z
  - Alt+Tab, Alt+F4 and Ctrl+Alt+Delete
  - Win+anything
- Prefer Ctrl+Alt+key, Alt+key and Alt+Shift+key.
- Make combos easy to remember:
  - use the first letter, or a key the output looks like (Ctrl+Alt+E for €, Alt+A for α)
  - use Shift for a variant (Alt+2 → ², Alt+Shift+2 → ₂)
  - use arrow keys for arrows

## "text": what gets typed

- Any Unicode text from 1 to 10,000 characters: a symbol, an emoji, a word or whole sentences.
- Write a line break as \n (Kemper presses Enter there). Escape " and \ the way JSON requires.

## What the person does with your reply

They copy your reply into Kemper (Keypack Editor → AI → paste), or save the JSON as a file ending in .kmppck and double-click it. Kemper then shows every shortcut and any conflicts before importing.

## Example

Request: "Greek letters for my math notes: alpha, beta, pi and sigma, plus capital sigma."

```json
{
  "format": "kemper-keypack",
  "version": 1,
  "name": "Greek letters for math",
  "mappings": [
    { "keys": "Alt+A", "text": "α" },
    { "keys": "Alt+B", "text": "β" },
    { "keys": "Alt+P", "text": "π" },
    { "keys": "Alt+S", "text": "σ" },
    { "keys": "Alt+Shift+S", "text": "Σ" }
  ]
}
```

| Press | Types |
|---|---|
| Alt+A | α |
| Alt+B | β |
| Alt+P | π |
| Alt+S | σ |
| Alt+Shift+S | Σ |
````
