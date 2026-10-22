# ZT-0b063878d334 -- settings_export: Warn if some accounts will be unusable.

- lang: web   issue: #34275   tier: B
- fix: https://github.com/zulip/zulip/commit/0b063878d3347a60be34d74bdba9e00c0a4eba9f
- f2p: web/tests/people.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real feature work (warning users about accounts that become unusable after export) that a Zulip contributor would plausibly be assigned, backed by a high-priority upstream issue. The hidden test grades the new people.get_users_that_match_role_ids helper on observable behavior: it fails before the change (function absent) and passes after, asserting role-filtered user sets via deepEqual on Set comparisons rather than pinning exact output strings, HTML snapshots, or ordering. No brittleness flags apply \u2014 no rendered-template assertions, no i18n string pinning, no version/time gating."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "web/src/people.ts exports a new function `get_users_that_match_role_ids(user_ids: Set<number>, role_ids: Set<number>): User[]` \u2014 given a set of user IDs and a set of role codes, it returns the User objects (looked up among known users) whose `role` matches one of the given role codes; users whose role is not in the set (or who can't be resolved) are omitted.",
    "The role codes passed in are the pre-existing `settings_config.user_role_values.<role>.code` values (admin, owner, moderator, etc.) \u2014 the function filters on the user's existing `role` field against these codes; no new sentinel values are introduced.",
    "Return-order is not part of the contract: the test compares results as Sets, so any ordering of the matching users passes."
  ],
  "reason": "The test binds to exactly one new name: an exported helper `get_users_that_match_role_ids` on the shared `people` module, with a (Set<number>, Set<number>) -> User[] signature. In Zulip's web codebase, exported functions on people.ts are the module's public utility surface, and a ticket for the export-modal warning feature could legitimately dictate 'add this helper to people.ts with these semantics'. Everything else the test uses (people.add_active_user, settings_config.user_role_values codes, the User fixtures) pre-exists at the base commit. Given the contract above in the brief, the test grades filtering correctness \u2014 role matching, multi-role union, exclusion of non-matching users \u2014 not name-guessing. Notably, the test does not touch the genuinely internal parts of the fix (the private settings_exports helpers, the template name, the DOM container id, or the warning wording), so no incurable internal coupling exists."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product requirements concretely (remove the blocking error, exact note wording, conditions for each note), and the evidence plus interface requirements pin down the new people.ts helper's name, signature, and filtering semantics, so two engineers working independently would produce compatible implementations."
}
