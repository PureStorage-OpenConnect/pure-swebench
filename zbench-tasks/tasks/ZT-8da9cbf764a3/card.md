# ZT-8da9cbf764a3 -- compose: Add Ctrl+]/[ shortcuts for list indent/unindent

- lang: web   issue: #37738   tier: B
- fix: https://github.com/zulip/zulip/commit/8da9cbf764a3515c970e58c6334eaa1a34cac76e
- f2p: web/tests/compose_ui.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Real, plausibly-assigned compose feature (Ctrl+]/[ list indent shortcuts) with a deterministic hidden test that exercises the exported handle_list_indent function on concrete textarea values and asserts observable outcomes: transformed textarea content, return values for list vs non-list context, and multi-line/numbered-list cases. Assertions are short behavioral strings the fix directly produces, not pinned snapshots or incidental formatting, so it fails-before/passes-after cleanly."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The `compose_ui` module gains an exported function `handle_list_indent($textarea, increase)` where `$textarea` is a jQuery-wrapped textarea and `increase` is a boolean (true = indent, false = dedent). It implements the Ctrl+]/Ctrl+[ list-indentation feature and is the seam the keydown handler calls.",
    "Return value semantics: the function returns true when the selected line(s) constitute list context (bulleted `- ` or numbered `1. ` items, possibly already indented), meaning the keyboard shortcut should be consumed; it returns false when the cursor is on a non-list line, in which case the text must be left completely unchanged.",
    "Dedenting an unindented list item is still list context: the text may be unchanged but the function must return true (so the shortcut is still consumed).",
    "Indentation unit is 2 spaces per list line; dedent removes up to 2 leading spaces from a line.",
    "The operation applies to every full line touched by the selection: with a multi-line selection spanning several list items, each list line is indented/dedented; with a collapsed cursor, only the containing line is affected.",
    "List detection must recognize both bulleted (`- `) and numbered (`1. `) items, including items that already carry leading indentation.",
    "The function operates on the underlying DOM textarea element ($textarea[0]) using its value/selectionStart/selectionEnd and restores the selection via setSelectionRange; text updates go through the standard text-field-edit `setFieldText` helper (the codebase's established mechanism for programmatic textarea edits) or equivalently by setting the element's value."
  ],
  "reason": "The test binds only to one new exported function on an existing public module (`compose_ui.handle_list_indent`), its boolean parameter, its return-value semantics, and user-visible text-transformation behavior (2-space indent/dedent of bulleted/numbered list lines across the selection). These are exactly the things a feature ticket for a Ctrl+]/Ctrl+[ list-indent shortcut would pin down. The `setFieldText` override is a neutralizing stub of a pre-existing third-party helper already used throughout compose_ui, and a direct `value` assignment also passes, so it does not force an internal choice. The new `is_list_item` helper in bulleted_numbered_list_util is not referenced by the test, and the minimal fake jQuery object only requires the natural DOM-element access pattern that selection handling necessitates anyway. Given the contract above, the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives clear motivation and the evidence plus interface requirements pin down the exact function name, signature, return-value semantics, indent unit, multi-line selection behavior, list-marker detection (bulleted and numbered), non-list no-op behavior, and the Ctrl+]/Ctrl+[ key bindings \u2014 enough for two engineers to independently build compatible implementations."
}
