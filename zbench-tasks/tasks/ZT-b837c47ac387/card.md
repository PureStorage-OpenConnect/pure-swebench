# ZT-b837c47ac387 -- hotkey: Support non-latin keyboard locales for shortcuts.

- lang: web   issue: #19605   tier: B
- fix: https://github.com/zulip/zulip/commit/b837c47ac3872582830f2814ca8ce222f6b7b523
- f2p: web/tests/hotkey.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix / behavior-affecting feature (frontend keyboard handling)",
  "reason": "Real, plausibly-assigned engineering task (high-priority issue: hotkeys broken on non-Latin layouts) with an observable behavioral outcome: given a keydown event with a Cyrillic e.key and a physical e.code, get_keydown_hotkey must resolve the correct shortcut. The hidden test is a deterministic unit test asserting specific hotkey names and undefined for negative cases \u2014 it grades behavior (input event \u2192 resolved action) rather than pinning output strings, snapshots, or incidental formatting. Fails before the change, passes after, fully deterministic."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test only calls the pre-existing exported function hotkey.get_keydown_hotkey with standard DOM KeyboardEvent fields (key, code, shiftKey, ctrlKey, metaKey, altKey) and asserts pre-existing hotkey action names already used by the base-commit 'mappings' test. No new identifiers from the fix (CODE_TO_QWERTY_CHAR, is_printable_ascii, etc.) are referenced or mocked; all assertions follow behaviorally from the requirement that hotkeys on non-Latin layouts resolve via the physical key (event.code) to their QWERTY equivalents, including shift/Caps Lock and macOS Cmd semantics. Any correct implementation passes."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives the exact intended algorithm (prefer event.key for ASCII/named keys, fall back to event.code interpreted as QWERTY), and the expected-behavior evidence pins down the checkable details: shift/Caps Lock handling driven by the shiftKey flag, macOS Cmd-vs-Ctrl semantics, punctuation codes like BracketLeft, multi-action bindings, and which Ctrl chords must remain unmatched. Together these determine a concrete, verifiable outcome."
}
