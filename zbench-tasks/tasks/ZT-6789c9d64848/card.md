# ZT-6789c9d64848 -- search: Add "x" button to the filter of uploaded files table.

- lang: web   issue: #32599   tier: B
- fix: https://github.com/zulip/zulip/commit/6789c9d6484848ccae6b1f13f04d6d33e561e58e
- f2p: web/tests/list_widget.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real feature work (adding a clear-'x' button to settings table filters) with core logic in list_widget.ts. The hidden test grades observable, deterministic behavior: clicking the clear button restores the unfiltered list (get_current_list() equals the full list) and re-creating the widget detaches the old click handler. The mocked-jQuery assertions (event names, .clear-filter sibling selector) follow the existing test-file idiom and are not exact-string/snapshot pins, so the test is not brittle in the disqualifying sense."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "Each list-widget filter/search input gains a clear button rendered as a SIBLING element of the input, identified by the CSS class `clear-filter` (introduced via a shared `filter_text_input` template partial).",
    "In ListWidget.create's event setup, when a filter element is configured, the widget binds a direct `click` handler on the clear button obtained via `opts.filter.$element.siblings(\".clear-filter\")` (not a delegated container handler).",
    "Clicking the clear button empties the filter input (sets its value to \"\"), resets the widget's filter value to the empty string, and redraws, so that `widget.get_current_list()` returns the full unfiltered list afterwards.",
    "`clear_event_handlers` (invoked when ListWidget.create is called again on the same container) must also unbind the clear-button handler by calling `.off(\"click\")` on the element obtained via `$element.siblings(\".clear-filter\")`, alongside the existing input/sort/scroll handler cleanup."
  ],
  "reason": "The behavioral assertions ride on pre-existing public surface (ListWidget.create, get_current_list, the established clear_event_handlers re-registration semantics), so the only new bindings are the `.clear-filter` DOM class, its sibling relationship to the filter input, and the click bind/unbind lifecycle. A DOM class and placement for a new user-visible UI element is exactly what a ticket/design spec would dictate, and the zjquery mock's pinning of `siblings(\".clear-filter\")` is the direct idiomatic expression of the specified 'sibling with class clear-filter' relationship rather than a private helper or internal data structure. Given these contract items in the brief, the test grades correct behavior (clear resets the list; handlers are cleaned up on re-create), not name-guessing. Note the reference fix's settings_users.ts delegated-handler variant is untested by this diff, so the pinned direct-binding requirement must appear in the brief, as listed above."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product goal (clear button, shown only when non-empty, zulip-icon-close), and the evidence plus interface requirements pin down the exact DOM relationship (sibling with class .clear-filter), the binding/unbinding contract in ListWidget.create and clear_event_handlers, and the observable outcome of clicking clear (empty input, reset filter, full list redrawn). Two engineers following this brief would produce compatible implementations."
}
