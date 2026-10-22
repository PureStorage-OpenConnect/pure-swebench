# ZT-b7ce31135d20 -- deactivated_user: Correctly display deactivated users in the right sidebar.

- lang: web   issue: #30797   tier: B
- fix: https://github.com/zulip/zulip/commit/b7ce31135d20f699376a938ebd7337b85ba045e0
- f2p: web/tests/buddy_data.test.cjs, web/tests/user_events.test.cjs
- p2p: web/tests/buddy_list.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned bug fix changing observable frontend behavior: deactivated users are now shown (with a distinct 'user-circle-deactivated' indicator) in DM narrows instead of being hidden everywhere, and human subscriber counts include deactivated users. The hidden tests grade outcomes deterministically \u2014 get_user_circle_class(id, true) returning 'user-circle-deactivated' and the buddy list update path on deactivation events \u2014 which fail before and pass after the change. No exact-string snapshots, no HTML dumps, no version/time gating; assertions target small, stable return values rather than incidental formatting."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "buddy_data.get_user_circle_class gains an optional second boolean parameter (default false); when true, the function returns the CSS class \"user-circle-deactivated\" unconditionally, ignoring the user's presence status.",
    "Deactivated users shown in the buddy list are marked with the CSS class \"user-circle-deactivated\" on their user-circle indicator (rendered as a ban icon instead of a presence circle).",
    "A deactivated user's buddy-list sort level is unchanged by the deactivated indicator: buddy_data.level continues to return 3 (the offline level) for a user with no presence, whether or not they are deactivated.",
    "When a user's is_active status changes (deactivation or reactivation), the user must no longer be removed from the buddy list via buddy_list.maybe_remove_user_id; instead their row position must be updated by calling the existing buddy_list.insert_or_move([user_id]), and no other buddy_list module functions may be invoked on this code path."
  ],
  "reason": "The test binds only to contract surface a brief would dictate: a new boolean option and return value on the already-public buddy_data.get_user_circle_class export, the user-facing CSS class 'user-circle-deactivated', and the requirement that the deactivation event path use the pre-existing buddy_list.insert_or_move API instead of removing the user. The buddy_list module stub mirrors structure that exists at the base commit (BuddyList class, buddy_list singleton, insert_or_move method) rather than internals invented by the fix, and it asserts no call sequence \u2014 it only constrains which pre-existing API the path may touch. No private helper names, invented internal fields, or fix-specific module layout are required."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue plus the behavioral evidence pin down a determinate, checkable outcome: a new optional boolean on get_user_circle_class returning 'user-circle-deactivated', unchanged level() semantics, and the is_active event path switching from maybe_remove_user_id to insert_or_move([user_id]). The issue supplies the product context (DM-only visibility, ban icon, counts)."
}
