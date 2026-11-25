# Kemper Marketplace

Ready-made keypacks for [Kemper](../README.md). Download one, double-click it, and Kemper shows every shortcut in it before importing anything.

**Every keypack here works with every other one.** No two of them share a combo, so you can import all of them at once. None of them uses Kemper's quick picker combo (Ctrl + Alt + K), or the keys every app needs, like Ctrl + C.

Browse them with a preview of every shortcut at **[kemper.talken.in/#marketplace](https://kemper.talken.in/#marketplace)**.

| Keypack | What you get | Combos | |
|---|---|---|---|
| [Super & subscripts](superscripts-subscripts.kmppck) | ⁰ ¹ ² ³ … ₀ ₁ ₂ ₃ … for x², H₂O, CO₂ | Alt + digit, Alt + Shift + digit | [Download](https://kemper.talken.in/marketplace/superscripts-subscripts.kmppck) |
| [Greek letters](greek.kmppck) | α β γ δ ε θ λ μ π σ φ ω, capitals Γ Δ Θ Λ Π Σ Φ Ω | Alt + letter, Alt + Shift + letter | [Download](https://kemper.talken.in/marketplace/greek.kmppck) |
| [Math symbols](math.kmppck) | ≠ ± × ÷ ≤ ≥ ≈ ∞ √ ∫ ° ½ ⅓ ¼ | Ctrl + Alt + key | [Download](https://kemper.talken.in/marketplace/math.kmppck) |
| [Arrows](arrows.kmppck) | ← → ↑ ↓ ⇐ ⇒ ⇑ ⇓ | Ctrl + Alt + arrow keys | [Download](https://kemper.talken.in/marketplace/arrows.kmppck) |
| [Currency symbols](currency.kmppck) | € £ ¥ ₹ ₩ ₿ ¢ | Ctrl + Alt + letter | [Download](https://kemper.talken.in/marketplace/currency.kmppck) |
| [Typography](typography.kmppck) | – — … “ ” ‘ ’ • © ® ™ | Ctrl + Alt + key | [Download](https://kemper.talken.in/marketplace/typography.kmppck) |
| [Everyday emoji](emoji.kmppck) | 👍 ❤️ 😂 🙏 🎉 🔥 ✅ 😊 👀 ❌ | Ctrl + Alt + digit | [Download](https://kemper.talken.in/marketplace/emoji.kmppck) |
| [Text faces](text-faces.kmppck) | ¯\\\_(ツ)\_/¯ (╯°□°)╯︵ ┻━┻ ಠ\_ಠ | Ctrl + Alt + Shift + letter | [Download](https://kemper.talken.in/marketplace/text-faces.kmppck) |

## Installing a keypack

1. Click **Download** next to the keypack.
2. Double-click the downloaded `.kmppck` file. You can also use **Keypacks → Import a keypack…** in Kemper's window, or run `python kemper.pyw --keypack greek.kmppck`.
3. Kemper lists every shortcut in the keypack and marks any that clash with yours. Click **Import**.

Don't like a combo? Change it in Kemper's window after importing.

**Keyboards with an AltGr key.** On many European layouts, AltGr is the same as Ctrl + Alt. A keypack on Ctrl + Alt can take over a character you type with AltGr, like `@` or `{` on a German keyboard. Kemper's import shows exactly which combos a keypack uses, so skip or change those.

**Greek letters and app menus.** Some apps open their menus with Alt + a letter, like Alt + F for File. With the Greek keypack, those combos type Greek instead. Press and release Alt, then the letter, to reach the menus.

## Adding your keypack

Made a keypack other people would like? Add it here with a pull request:

1. Put your `.kmppck` file in this folder. Use a short file name in lowercase with dashes, like `music-symbols.kmppck`.
2. Give the keypack a `"description"`: one sentence about what it's for.
3. Add a row for it to the table above.
4. Run `python test_kemper.py`. It checks that your keypack loads, is listed here, and doesn't clash with any keypack already in the Marketplace.

Need help making one? **Keypacks → Create a keypack** opens the Keypack Editor, and an AI chat can write one for you with [these instructions](../docs/AI_INSTRUCTIONS.md). See [CONTRIBUTING.md](../CONTRIBUTING.md#adding-a-keypack-to-the-marketplace) for more.
