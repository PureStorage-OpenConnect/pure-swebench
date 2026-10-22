# Add keyboard shortcuts to increase/decrease list item indentation in the compose box

## Background

When composing a message in Zulip's compose box, a user writing a Markdown list has no quick way to change an item's nesting level. For example, while writing:

```
- Item 1
- Item 2
- Item 3
```

pressing Shift + Enter starts a new list item, but to turn it into a sub-item the user must manually type two spaces at the start of the line. There is currently no keyboard shortcut to increase or decrease the indentation of the current list item.

## Required behavior

Add keyboard shortcuts to the message-composition textarea:

- **Ctrl + ]** increases the indentation level of the list item(s) under the cursor/selection.
- **Ctrl + [** decreases the indentation level of the list item(s) under the cursor/selection.

Detailed semantics:

1. **Indent unit.** One indentation level is exactly 2 spaces. Indenting prepends 2 spaces to the start of the affected line(s). Dedenting removes up to 2 leading spaces from each affected line (a line with only 1 leading space loses that 1 space; a line with none is unchanged).
2. **Affected lines.** The operation applies to every full line touched by the current selection. With a collapsed cursor, only the line containing the cursor is affected. With a multi-line selection, every line the selection touches (from the start of the first touched line to the end of the last) is indented/dedented, e.g. selecting all of `- Item 1\n- Item 2\n- Item 3` and indenting yields `  - Item 1\n  - Item 2\n  - Item 3`.
3. **List detection.** The shortcut only acts when the affected line(s) are list items. A list item is a line beginning with a bullet marker (`- `) or a numbered marker (e.g. `1. `), optionally preceded by leading spaces (already-indented items still count). Cursor position within the line does not matter — e.g. a cursor at the end of `- Item 2` in `- Item 1\n- Item 2` followed by indent produces `- Item 1\n  - Item 2`; an unindented `1. Item 1` with the cursor at position 0 indents to `  1. Item 1`.
4. **Non-list lines.** If the cursor/selection is not on list-item line(s) (e.g. cursor in the middle of `Hello world`), the shortcut must do nothing: the text is left completely unchanged and the key event is NOT consumed (default browser behavior proceeds).
5. **No-op dedents still count as list context.** Dedenting a list item that has no leading indentation (e.g. cursor inside `- Item 1`) may leave the text unchanged, but it is still treated as a handled list operation — the key event IS consumed.
6. **Selection/cursor preservation.** After indenting/dedenting, the selection (or collapsed cursor) must be restored to cover the same logical text, adjusted for the inserted/removed spaces, via the element's `setSelectionRange`.
7. **Undo-friendliness.** Text updates must go through the codebase's standard programmatic-textarea-edit mechanism, the `text_field_edit` module's `setFieldText` helper (the established pattern for edits that preserve native undo history), operating on the underlying DOM textarea element (`$textarea[0]`) and its `value` / `selectionStart` / `selectionEnd`.

The shortcuts should be wired into the compose box's keydown handling and documented alongside other compose keyboard shortcuts where applicable (e.g. the in-app keyboard shortcuts reference).

## Interface requirements

- The `compose_ui` module must export a function `handle_list_indent($textarea, increase)`, where `$textarea` is a jQuery-wrapped textarea and `increase` is a boolean (`true` = indent, `false` = dedent). This function implements the Ctrl+]/Ctrl+[ list-indentation behavior described above and is the entry point the keydown handler calls.
- **Return value:** `handle_list_indent` returns `true` when the selected line(s) constitute list context (bulleted `- ` or numbered `1. ` items, possibly already indented), signaling that the keyboard shortcut should be consumed. It returns `false` when the cursor is on a non-list line, in which case the text must be left completely unchanged.
- Dedenting an unindented list item is still list context: the text may be unchanged, but the function must return `true` so the shortcut is still consumed.
- Indentation unit is 2 spaces per list line; dedent removes up to 2 leading spaces per line.
- The operation applies to every full line touched by the selection: a multi-line selection spanning several list items indents/dedents each list line; a collapsed cursor affects only its containing line.
- List detection must recognize both bulleted (`- `) and numbered (`1. `) items, including items that already carry leading indentation.
- The function operates on the underlying DOM textarea element (`$textarea[0]`) using its `value`/`selectionStart`/`selectionEnd`, restores the selection via `setSelectionRange`, and applies text updates through the standard `text_field_edit` `setFieldText` helper (or equivalently by setting the element's `value`).
