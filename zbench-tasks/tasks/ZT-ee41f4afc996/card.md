# ZT-ee41f4afc996 -- typeahead: Support @-prefixed queries for user groups.

- lang: web   issue: #22448   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/ee41f4afc9961ef106fe444ba3a73172bd2ca76c
- f2p: web/tests/pill_typeahead.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavioral bug fix / small well-specified improvement (frontend typeahead)",
  "reason": "The change adds observable behavior \u2014 @-prefixed queries in the combined pill typeahead now match user groups (with the prefix stripped for matching and sorting) instead of returning nothing \u2014 implemented through the pre-existing set_up_combined source/matcher/sorter interfaces. It is tied to a concrete issue, small in scope (2 files, ~43 lines), and readily assertable by hidden node tests that feed queries like \"@groupname\" and check the returned suggestions, with no refactor, i18n, docs, schema, migration, or version-gating concerns."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "The hidden test exercises only pre-existing interfaces: config.source/matcher/sorter from set_up_combined, and it rewires typeahead_helper.sort_stream_or_group_members_options, which the code diff's context lines show already exists at the base commit (the fix only changes the query value passed to it). The item.type === 'user_group' discriminant also pre-exists \u2014 the base version of both matcher and source already use it, as visible in unchanged diff context. The new assertions check behavior the issue implies (@-prefixed queries yield/match only user groups, and the sorter receives a query with the '@' stripped, asserted via !query.startsWith('@')) rather than any new symbol name, constant, or error string invented by the fix. A solver could satisfy these tests with any implementation of the @-prefix semantics, not just the author's exact code."
}
