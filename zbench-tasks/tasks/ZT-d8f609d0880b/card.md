# ZT-d8f609d0880b -- unresolved: Add support for searching for unresolved topics.

- lang: web   issue: #31725   tier: B
- fix: https://github.com/zulip/zulip/commit/d8f609d0880b2b03b7bfe09a709b10a4d4b7b7a4
- f2p: web/tests/filter.test.cjs, web/tests/search_suggestion.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, plausibly-assigned search UX feature: negated is:resolved gets a dedicated 'unresolved topics' phrasing and a '-is:resolved' suggestion. The hidden tests grade observable, deterministic behavior \u2014 the filter description output for a negated term and the presence/description of the new suggestion in the suggestion list. The string assertions are short, targeted phrases that ARE the behavior being changed (not long pinned snapshots or rendered-HTML dumps), and they fail-before/pass-after cleanly."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The search-bar narrow description for `is:resolved` (as returned by the existing Filter.search_description_as_html) must read exactly \"resolved topics\" (changed from \"topics marked as resolved\").",
    "A negated `is:resolved` term ({operator: \"is\", operand: \"resolved\", negated: true}) must be described as exactly \"unresolved topics\" \u2014 using the natural negative word instead of the default \"exclude \" prefix.",
    "The search typeahead must offer a suggestion with search string `-is:resolved` whose description reads \"Unresolved topics\" (rendered with sentence-case capitalization in the suggestion line), replacing the generic \"Exclude topics marked as resolved\" wording.",
    "The suggestion list for an empty search query must include `-is:resolved`, placed immediately after the `is:resolved` suggestion and before the sender/channel suggestions.",
    "Other negated `is:` suggestions keep the default \"Exclude ...\" phrasing (e.g. `-is:followed` \u2192 \"Exclude followed topics\"); only operands with a natural negative word (currently \"resolved\") get special wording."
  ],
  "reason": "All assertions go through interfaces that exist at the base commit (Filter.search_description_as_html and the search-suggestion getters); the test binds to no private helpers, mocks of internals, or invented data-structure names. What it does pin is exact new user-facing copy (\"resolved topics\", \"unresolved topics\", \"Unresolved topics\") and the presence/position of a new `-is:resolved` suggestion \u2014 precisely the kind of user-facing message and UI-behavior detail a ticket would spell out. Given those requirements in the brief, the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue plus the observable-behavior evidence and interface requirements pin down exact strings, the exact suggestion ordering for empty queries, and the scope boundary (only 'resolved' gets natural-negative wording), so two engineers would independently produce compatible implementations."
}
