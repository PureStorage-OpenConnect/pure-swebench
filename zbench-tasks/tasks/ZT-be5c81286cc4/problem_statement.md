# Fix truncated markers in ordered lists with 3+ digit numbers

## Background

Zulip renders user-composed Markdown into HTML for display, both in the message-compose preview and in sent messages. Ordered lists render as standard `<ol>`/`<li>` HTML, where the `<ol>` may carry a `start` attribute when the list doesn't begin at 1 (e.g. a list written as `99. first / 100. second` renders as `<ol start="99">…`).

## Problem

The CSS for rendered message content lays out ordered lists with a fixed margin/indentation sized to fit list markers of at most two digits. When a list's counters reach three or more digits (either a long list, or one with a large `start` value), the leading digits of the markers are visually cut off, because the marker area is too narrow. This affects both the Markdown preview in the compose box and rendered sent messages.

Naive CSS-only approaches (e.g. simply widening the margin for all lists, or relying on marker-box auto-sizing) have proven inadequate: they either misalign short lists or don't account for the actual number of digits a given list needs. The fix should size the marker area per-list based on how many digits that particular list's counters actually require.

## Required behavior

Numbered lists must display fully, with no digits of any marker cut off, regardless of how many digits the counters have. Lists with small counters should keep their current compact indentation; only lists that need wider markers should get more space.

To enable digit-aware styling, the client-side HTML postprocessing step that Zulip already applies to rendered message content (before insertion into the DOM) must annotate every ordered list with a class indicating how many digits its widest counter needs. CSS can then key off that class to reserve the right amount of marker space. The same postprocessing (and therefore the same visual result) must apply to both message rendering and compose preview, since both flow through the same content pipeline.

### Annotation rules

For every `<ol>` element in rendered message content:

1. Determine the starting counter value: the value of the `start` attribute if present, otherwise 1.
2. Determine the largest counter value the list will display: `start + (number of child list items) - 1`.
3. Compute `N`, the number of decimal digits in that largest counter value.
4. Add the CSS class `counter-length-<N>` to the `<ol>`.

Examples:
- `<ol><li>a</li><li>b</li></ol>` → max counter 2 → class `counter-length-1`.
- `<ol start="9"><li>Nine</li><li>Ten</li></ol>` → max counter 9 + 2 − 1 = 10 → class `counter-length-2`.
- A list starting at 98 with 5 items → max counter 102 → class `counter-length-3`.

The class must be appended to the element's existing attributes; the `start` attribute (when present) and the list's contents must otherwise pass through unchanged. So the second example above must produce exactly `<ol start="9" class="counter-length-2"><li>Nine</li><li>Ten</li></ol>`. Nested ordered lists are each annotated independently based on their own start value and item count.

Accompanying CSS must use these classes so that each ordered list in message content and preview reserves marker space appropriate to its digit count — wide enough that no marker is clipped, without over-indenting short lists.

## Interface requirements

- `postprocess_content` (the pre-existing HTML postprocessing entry point) adds a CSS class of the form `counter-length-<N>` to every `<ol>` element in the rendered message content.
- `<N>` is the number of decimal digits in the largest list-item counter value, computed as (the ol's `start` attribute, defaulting to 1 when absent) + (number of child items) - 1; e.g. start=9 with 2 items gives max counter 10, so class `counter-length-2`.
- The class is appended to the ol's existing attributes; the `start` attribute and list contents are otherwise preserved unchanged.
