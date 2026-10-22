# ZT-53cdfddf5bb9 -- groups-ui: Add option to copy membership from group.

- lang: web   issue: #32335   tier: B
- fix: https://github.com/zulip/zulip/commit/53cdfddf5bb950dccadd804e7cd63e9478946c37
- f2p: web/tests/pill_typeahead.test.cjs, web/tests/user_group_pill.test.cjs
- p2p: web/tests/input_pill.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature (web client)",
  "reason": "Real, assignable feature: an 'expand group pill into its members' affordance in the group-members input. The hidden grader is deterministic Node unit tests (pill_typeahead, user_group_pill) that assert observable pill state \u2014 e.g. the new show_expand_button property on appended group pills and the Set-based membership handling \u2014 which fail before the change and pass after. It is not an HTML/JSON snapshot pin, not CSS-only layout, and not format-brittle; frontend behavior here is graded via data-level assertions, which is acceptable."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "User group pill items (the exported UserGroupPill data carried by pill widgets) gain an optional boolean field `show_expand_button`, indicating whether the pill renders a control to expand the group into its members/subgroups; pills created without expansion enabled carry `show_expand_button: false`."
  ],
  "reason": "The user_group_pill test binds to exactly one new name: the `show_expand_button` boolean on the UserGroupPill item, including its false default. UserGroupPill is an exported cross-module type in the web frontend (set by add_group_members_pill.ts, consumed by templates), so a design spec for the 'expand group pill' feature would legitimately pin this field name and its default sentinel \u2014 handed this requirement, a solver is graded on correctness, not name-guessing. The other test change (members: array \u2192 Set in pill_typeahead fixtures) is not new surface at all: Zulip's pre-existing UserGroup type already defines `members` as a Set of user IDs, so the fixtures are merely being corrected to conform to the existing interface that the fix now exercises via `.size`. No test binds to private helpers (expand_group_pill is untested by name), internal hook wiring (onPillExpand), mock targets, or module layout."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product intent (a button on the group input pill that explodes it into its members), the interface requirement pins the exact data-model addition (`show_expand_button` on UserGroupPill, explicit false when disabled), and the behavior evidence confirms both the explicit-false default on non-expansion pill creation paths and that group membership is consumed as a Set of user IDs. Together these determine a concrete, checkable outcome; only fine UI details (icon choice, exact placement) are left to the implementer, which is acceptable."
}
