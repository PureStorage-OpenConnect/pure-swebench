# ZT-6f196c7ec97e -- composebox_typeahead: Show CrossRealmBots in the typeahead list.

- lang: web   issue: #30817   tier: B
- fix: https://github.com/zulip/zulip/commit/6f196c7ec97e0f3894d16ca01b722bbcdd964169
- f2p: web/tests/composebox_typeahead.test.cjs
- p2p: web/tests/people.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned bug fix: cross-realm system bots (Welcome Bot, Notification Bot) missing from compose typeahead suggestions. The hidden test grades observable behavior deterministically \u2014 it asserts which user items appear (and in what deterministic sorted order) in the typeahead result lists for various queries, using the test suite's established assert_typeahead_equals/deepEqual-on-item-lists idiom rather than pinning rendered HTML, long output strings, or snapshots. The test fails before the fix (bots absent from suggestions) and passes after, and the ordering is governed by the deterministic sort_recipients logic, not incidental formatting."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test never references any name invented by the fix. The code diff's new helpers (get_realm_users_and_welcome_bot, get_realm_users_and_system_bots) and the added get_person_suggestions parameter are internal choices the test does not touch. The test builds its fixtures with pre-existing public APIs (people.add_cross_realm_user, people.add_active_user \u2014 cross_realm_dict and the is_system_bot user field already exist in Zulip's people module at base) and asserts only user-visible outcomes: which suggestions the composebox mention/DM typeahead returns for '@'-style queries. The expected orderings (system bots appearing after users/wildcards) fall out of the pre-existing typeahead_helper.sort_recipients logic once the bots are included, so no author-only ordering choice is encoded. The behavioral requirement itself \u2014 system bots appear in mention typeahead, only Welcome Bot in DM recipient typeahead \u2014 is the task's user-facing behavior that any ticket would state, checked entirely through interfaces that exist at the base commit."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user-facing gap (cross-realm bots absent from typeaheads) and the evidence pins down the checkable contract: bots sourced from the cross-realm user store, matched with normal person-matching rules, shown for both regular and silent mentions, and ranked after users, wildcard mentions, and groups, alphabetically among themselves. That is determinate enough for two engineers to build compatible implementations."
}
