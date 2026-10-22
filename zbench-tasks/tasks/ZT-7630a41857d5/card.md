# ZT-7630a41857d5 -- left_sidebar: Switch topic filtering to any-order word prefix matching.

- lang: web   issue: #35160   tier: B
- fix: https://github.com/zulip/zulip/commit/7630a41857d5650c183d94b6b6b1c6efa641b059
- f2p: web/tests/topic_list_data.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior-affecting frontend change (search/filter logic)",
  "reason": "Real, plausibly-assigned engineering task: switching left-sidebar topic filtering from single-prefix matching to any-order word-prefix matching, driven by a labeled 'help wanted' issue. The hidden test grades observable behavior deterministically \u2014 given fixed topic fixtures, it asserts which topics match queries like 'ba de gu' vs 'gu ba de', that mid-word matches ('thent') fail, and case-insensitivity \u2014 all of which fail before the change and pass after. It pins no long output strings or snapshots; the few topic_name/ordering assertions are on tiny fixed fixtures whose order is determined by message recency, not incidental formatting."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test exercises only `get_list_info(zoomed, search_term)` via the pre-existing `topic_list_data` module \u2014 the exact interface the existing test file already used at the base commit. Every new assertion checks user-visible search-filtering outcomes (case-insensitive matching, word-prefix rather than substring matching ('thent' finds nothing), any-order multi-word queries ('ba de gu' vs 'gu ba de'), punctuation like '(' handled in queries, and result counts/topic names). It never references the fix's internal choices: not the `typeahead.query_matches_string_in_any_order` helper, not the `normalize` function, not the separator regex, and it stubs no internals. The assertions define the desired search semantics \u2014 which the task ticket itself would describe \u2014 through an existing public function, so no new names must be handed to the solver."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the goal (word-prefix matching in left sidebar filters, modeled on the right sidebar user search) and the evidence pins down the exact observable semantics: whitespace-split queries, case-insensitive word-prefix matching, any-order matching (the evidence shows out-of-order queries like 'gu ba de' and 'Developer Backend' matching, overriding the issue's tentative in-order suggestion for topics), literal punctuation handling, rejection of mid-word matches, preservation of recency ordering, and the empty-string/'general' topic special case. This is determinate and checkable."
}
