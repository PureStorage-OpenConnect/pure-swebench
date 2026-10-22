# Stop inserting a blank line *before* lists created with the compose-box formatting buttons

## Context

Zulip's compose box has toolbar buttons (also reachable via keyboard shortcuts) for formatting the current selection as a **bulleted list** or a **numbered list**. This logic lives in the compose formatting code in `web/src/compose_ui.ts` (the `format_text` handling for the `"bulleted"` and `"numbered"` formatting types).

Today, when the selected text is converted into a list and there is other content adjacent to it in the textarea, the formatter inserts a blank line **both before and after** the newly created list, to visually demarcate it from the surrounding text.

The blank line **after** the list is genuinely needed: without it, the line that follows the list would be interpreted by the Markdown renderer as a continuation of the list's last item and rendered with an unexpected indent. The blank line **before** the list, however, is unnecessary for correct rendering and produces a worse editing experience (the cursor/content jumps further than the user expects, and an extra empty line accumulates in the message).

## Required behavior

Change the bulleted- and numbered-list formatting so that:

1. **No blank line is inserted before the list.** When the user applies bulleted or numbered formatting to selected lines that are preceded by other content, the list should start on the line immediately following that preceding content — no empty line in between.
2. **The blank line after the list is kept**, exactly as today: when content follows the list, a blank line must still separate the list's last item from that following content (to avoid the unwanted-indent problem described above).
3. **Selection behavior is unchanged in spirit:** after formatting, the selection should cover exactly the list lines that were created (from the start of the first list item's marker through the end of the last item), not the surrounding blank line or neighboring text.

### Concrete example

Textarea content, where `<` and `>` mark the user's selection:

```
before_first
first_<item
second>_item
after_last
```

Applying **numbered list** formatting must produce:

```
before_first
<1. first_item
2. second_item>

after_last
```

Note: there is **no** blank line between `before_first` and `1. first_item`, but there **is** still a blank line between `2. second_item` and `after_last`. (The previous behavior produced blank lines in both places.)

The same rule applies to bulleted lists (`* ` markers).

## Toggling off must handle the new layout

These formatting buttons are toggles: applying list formatting to lines that are already a list removes the list markers (and any demarcating blank lines that were added). Untoggling must work correctly for lists that are directly adjacent to preceding content, i.e. lists in the new no-blank-line-before layout.

Concrete example — toggling **off** bulleted formatting. Starting state (selection marked with `<`/`>`):

```
before_first
<* first_item
* second_item>
after_last
```

must become:

```
before_first
<first_item
second_item>
after_last
```

The bullet markers are removed, the surrounding `before_first`/`after_last` lines are untouched, no stray blank lines are introduced or left behind, and the selection covers the now-unformatted lines.

## Unchanged behavior

- Formatting a selection that has no surrounding content (the whole textarea is selected, or the list sits at the very start/end of the message) continues to work as before, minus any leading blank line that would previously have been added.
- All other formatting operations (bold, italic, links, quotes, code blocks, etc.) are out of scope and must not change.
- Any user-facing comments/documentation in the formatting code that describe blank lines being added both before and after the list should be updated to reflect that only the trailing blank line is added.
