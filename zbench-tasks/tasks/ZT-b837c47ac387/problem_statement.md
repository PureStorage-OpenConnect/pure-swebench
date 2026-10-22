# Make keyboard shortcuts work on non-Latin keyboard layouts

## Context

Zulip's web app dispatches keyboard shortcuts in `web/src/hotkey.ts`. The keydown resolver (`get_keydown_hotkey`) receives a browser `KeyboardEvent` and decides which shortcut action (if any) it maps to, based on the event's `key` value plus the `shiftKey`/`ctrlKey`/`metaKey`/`altKey` modifier flags.

## Problem

Shortcut resolution currently looks only at `event.key` — the character the pressed key would type. When the user's OS keyboard layout produces a non-Latin script (e.g. Russian/Cyrillic), pressing the physical key labeled both "Н" and "N" yields `event.key === "т"`-style Cyrillic characters, which match none of Zulip's shortcut bindings. As a result, essentially all keyboard shortcuts are dead for users typing in Cyrillic (and other non-Latin scripts) until they switch their OS layout to a Latin one.

## Required behavior

Adopt the convention used by most desktop apps, using both `event.key` and `event.code` (the physical-key identifier):

1. **Latin layouts: unchanged.** If `event.key` is an ASCII letter, ASCII punctuation, or one of the named key values the app already handles ("Escape", "Enter", "ArrowDown", etc.), resolve the shortcut from `event.key` exactly as today. This means a Dvorak user keeps using the key that types the letter, which may be a different physical key than on QWERTY.

2. **Non-Latin layouts: fall back to the physical key.** If `event.key` is not one of the values above (e.g. a Cyrillic letter), resolve the shortcut from `event.code` instead, interpreting the physical key as the character it would produce on a US-QWERTY layout, and then run the normal shortcut lookup on that character. So `code: "KeyN"` behaves like the letter "n", `code: "BracketLeft"` like "[", and so on — a Cyrillic-layout user presses the same physical keys a QWERTY user would.

3. **Shift on the fallback path.** Whether the fallback character is treated as lowercase or uppercase must be derived from the `shiftKey` flag, not from the case of `event.key`. This matters for Caps Lock: with Caps Lock on, a Russian layout reports an uppercase Cyrillic `event.key` with `shiftKey: false`, and shortcuts must still behave as if unshifted. Concretely (Russian layout examples):
    * `key: "о", code: "KeyJ"`, no modifiers → the "j" shortcut (cursor down / `vim_down`).
    * `key: "Ф", code: "KeyA", shiftKey: false` (Caps Lock) → the "a" shortcut (`open_combined_feed`), while the same with `shiftKey: true` → the "A" shortcut (`stream_cycle_backward`).
    * `key: "Р", code: "KeyH", shiftKey: true` → the Shift+H shortcut (`view_edit_history`); `key: "Т", code: "KeyN", shiftKey: true` → Shift+N (`narrow_to_next_unread_followed_topic`).

4. **Modifier semantics identical on both paths.** All existing modifier rules must apply unchanged when resolving via `event.code`:
    * `Ctrl+[` (e.g. `key: "х", code: "BracketLeft", ctrlKey: true`) → escape behavior, on all platforms via Ctrl (not Cmd).
    * The Ctrl-based letter shortcuts work: Ctrl+C (`copy_with_c`), Ctrl+K (`search_with_k`), Ctrl+S (`star_message`) — e.g. `key: "с", code: "KeyC", ctrlKey: true` copies.
    * On macOS, Cmd (`metaKey`) substitutes for Ctrl on those letter shortcuts exactly as it does today for Latin layouts (Cmd+C/K/S work, plain Ctrl+C/K/S do not, and Ctrl+Cmd together does not).
    * Alt-based shortcuts work, e.g. `key: "з", code: "KeyP", altKey: true` → `toggle_compose_preview`.
    * Adding Shift to a Ctrl/Alt chord that isn't a defined shortcut must not match anything (e.g. Ctrl+Shift+K, Ctrl+Shift+[, Alt+Shift+P resolve to nothing).

5. **No new false positives.** The fallback must only match combinations that are actual Zulip shortcuts. Ctrl chords the app deliberately leaves to the browser/OS (Ctrl+V, Ctrl+Z, Ctrl+A, Ctrl+F, Ctrl+X, Ctrl+P, Ctrl+R, Ctrl+T, Ctrl+O, Ctrl+H, Ctrl+N, Ctrl+M, etc.) must continue to resolve to nothing when pressed on a non-Latin layout.

6. **Multi-action bindings preserved.** Where a chord is bound to more than one candidate action (for example Shift+V resolves to both `view_selected_stream` and `toggle_read_receipts`), the fallback path must yield the same full ordered set of candidates as the Latin path (`key: "М", code: "KeyV", shiftKey: true` behaves exactly like Shift+V).

The resolver must keep accepting a keyboard-event-shaped object with `key`, `code`, `shiftKey`, `ctrlKey`, `metaKey`, and `altKey` fields and keep returning the same shape of result it does today (`undefined` when nothing matches; the matching hotkey spec(s), each carrying its `name`, when something does).

The fallback needs to cover at least every physical key used by an existing Zulip shortcut: all letter codes (`KeyA`–`KeyZ`) and the punctuation/digit codes the shortcut set uses (e.g. `BracketLeft` for "["), mapping each, combined with the Shift state, to the character a US-QWERTY layout would produce.

## Out of scope

* No changes to which shortcuts exist or to their Latin-layout behavior.
* No changes to shortcut behavior while focus is in text inputs beyond what already exists.
* Only keydown-based shortcut resolution needs the fallback; keypress-based handling of typed characters is unaffected.
