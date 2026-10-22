# Make ListWidget sorting stable across consecutive sorts (recent conversations resorting)

## Background

Zulip's web client renders many sortable tables (including the **Recent conversations** view) with the generic `ListWidget` component (`web/src/list_widget.ts`). Widgets can declare `sort_fields`, and sort buttons in a `$parent_container` let the user click a column to sort by it; clicking the already-active column toggles reverse (descending) mode, indicated by a `descend` class on the button.

## Current (buggy) behavior

Sorting is not *stable across re-sorts* the way it is in spreadsheets. When the widget redraws it always starts from the same base ordering of the source list, filters it, and then applies only the single currently-selected sorting function:

```
meta.filtered_list = get_filtered_items(meta.filter_value, meta.list, opts);
if (meta.sorting_function) {
    meta.filtered_list.sort(meta.sorting_function);
}
if (meta.reverse_mode) {
    meta.filtered_list.reverse();
}
```

Because each new sort is applied to the original base ordering rather than to the previously displayed ordering, any earlier sort's effect is discarded. Example in Recent conversations: sort by topic, then sort by channel — the rows are ordered by channel, but within each channel the topic ordering from the first sort is lost.

## Required behavior

Sorting must behave like stable multi-key sorting in spreadsheets. Concretely, `ListWidget` must keep track of the *ordered history of sort fields the user has applied*, and the displayed order must be equivalent to: start from the source list's original order, then apply each sort in the history in sequence using a stable sort (JavaScript's `Array.prototype.sort` is stable, so stability comes from sorting the previously sorted data rather than the base data).

Rules:

1. **Layered sorts.** Applying sort B after sort A must produce a list ordered by B, where items that compare equal under B keep their relative order from the A-sorted list (and, transitively, ties under earlier sorts fall back to the original list order).
2. **Re-applying an existing sort field.** If the user applies a sort field that is already somewhere in the history, the old occurrence is removed and the field is appended as the most recent sort. Example: after sorting by salary, then by name, sorting by salary again must order by salary with salary ties resolved by name (i.e., as if the history were name-then-salary), *not* by the pre-name salary ordering.
3. **Reverse toggling.** Clicking the sort control for the field that is already the active (most recent) sort toggles reverse mode: the currently displayed list is reversed element-for-element (including tied items), and the control gains the `descend` class. Selecting a different sort field turns reverse mode off (no `descend` class until that field is clicked a second time).
4. **Existing UI behavior preserved.** Activating a sort still deactivates the other sort buttons in the container, clears and re-renders the widget's container, and all existing single-sort behavior (initial sort, filtering, `generic_sort_functions` for `alphabetic`/`numeric` fields, custom sort callbacks) must continue to work unchanged.

### Worked example

Source list (in this order): alice/50, bob/40, cal/30, dave/20, ellen/95, bob_2 (name "bob")/20, cal_2 (name "cal")/60, with a numeric sort on `salary` and an alphabetic sort on `name`.

- Apply salary sort, then name sort → `alice, bob_2, bob, cal, cal_2, dave, ellen` (bob_2 precedes bob because it had the lower salary; cal precedes cal_2 for the same reason).
- Apply salary sort again (fresh selection of that column) → `bob_2, dave, cal, bob, alice, cal_2, ellen` (ordered by salary; the 20-salary tie between bob_2 and dave is broken by the name sort that is now earlier in the history).
- Click the salary control again (it is now the active sort) → the list reverses to `ellen, cal_2, alice, bob, cal, bob_2, dave` and the control shows the `descend` state.

## Scope notes

- The fix belongs in the generic `ListWidget` sorting logic so every consumer (Recent conversations, settings tables, etc.) benefits; do not special-case one view.
- The layered ordering must survive the widget's normal redraw path (which re-derives the filtered list from the source data), so the sort history — not a one-off mutation of the displayed array — must determine the resulting order.
