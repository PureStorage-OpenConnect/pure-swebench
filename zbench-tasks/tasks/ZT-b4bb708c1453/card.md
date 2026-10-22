# ZT-b4bb708c1453 -- recent_conversations: Improve sorting behavior.

- lang: web   issue: #33289   tier: B
- fix: https://github.com/zulip/zulip/commit/b4bb708c1453d0edfe2c4e82902480371c47134e
- f2p: web/tests/list_widget.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix / behavior improvement",
  "reason": "Real, plausibly-assigned frontend change: list_widget gains multi-level (stable, stacked) sorting so re-sorting in recent conversations preserves prior sort as a tiebreaker. The hidden test grades observable outcome deterministically \u2014 it applies sort buttons in sequence and asserts the resulting item order, which fails on the old single-sort behavior and passes after. The HTML comparison is built from the test's own tiny modifier over a fixed 7-item list (the file's established pattern), so it pins item ordering, not incidental long-format snapshots. No excluded category applies."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test drives the widget exclusively through pre-existing interfaces: ListWidget.create with the existing opts shape, the existing generic_sort_functions API, and the pre-existing sort-button click simulation ($sort_container.f.apply / sort_button) already used by the base-commit 'sorting' test. It asserts only user-visible outcomes: the rendered row order after consecutive sorts (prior sorts act as tiebreakers, re-sorting a field replaces its earlier application, second click reverses) plus the pre-existing 'descend' class and sibling-deactivation behavior. The fix's internal state (applied_sorting_functions array, its tuple layout) is never touched by the test, so no new names or internal choices must be guessed."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the user-visible problem and points at the exact ListWidget code path, and the expected-behavior evidence pins down determinate semantics: stable layering of consecutive sorts, move-to-front-of-recency when a field is re-applied (verifiable from the bob_2/dave tie-break), full-list reversal on toggling the active sort, and the 'descend' indicator. Together these give a concrete, checkable specification."
}
