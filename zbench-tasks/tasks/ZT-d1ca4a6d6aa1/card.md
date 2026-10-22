# ZT-d1ca4a6d6aa1 -- user: Update pills and pm_list on deactivation.

- lang: web   issue: #33376   tier: B
- fix: https://github.com/zulip/zulip/commit/d1ca4a6d6aa177f7e592f6b5b4556b95d205a640
- f2p: web/tests/user_events.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real live-update bug: deactivating/reactivating a user didn't refresh PM list or compose pills. The hidden test deterministically verifies the observable outcome (update functions invoked with the correct user and is_active flag on both deactivation and reactivation, for humans and bots) using standard Zulip node-test mocks \u2014 it fails before the fix and passes after, with no snapshot pinning, exact-string matching, or non-deterministic formatting."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The module `web/src/compose_pm_pill` gains a new exported function `update_user_pill_active_status(user, is_active)`, taking the affected user object (including its `user_id`) and a boolean `is_active`, which updates the compose box's recipient pill for that user to reflect whether the user is deactivated or active.",
    "When `user_events.update_person` processes a user-update event whose `is_active` field changes (deactivation or reactivation, for both human users and bots), it must call `compose_pm_pill.update_user_pill_active_status(user, is_active)` with the affected user's full user object and the new active status.",
    "When `user_events.update_person` processes a user-update event whose `is_active` field changes (deactivation or reactivation, for both human users and bots), it must refresh the direct-messages list by calling the existing `pm_list.update_private_messages()`."
  ],
  "reason": "The test drives everything through the pre-existing entry point `user_events.update_person` with real event payloads, so the trigger surface is existing API. It does, however, bind to one new name: `compose_pm_pill.update_user_pill_active_status(user, is_active)`, including its module location, argument order, and semantics (called with the full user object and the new boolean status on every activation change, for humans and bots alike). In Zulip's web codebase, exported module functions are the standard cross-module public API, and a ticket saying 'compose recipient pills must reflect user deactivation' would legitimately pin this function name and signature, so this is contract surface a brief can dictate rather than a private implementation detail. The test also requires that `pm_list.update_private_messages()` be invoked on activation changes; that function pre-exists as the canonical way to refresh the DM list, but since the test pins the mechanism (that specific call) rather than a user-visible outcome, it is included in the contract for safety. No private helpers, internal data structures, or invented module layout are asserted, so with these three requirements in the brief the test grades correctness, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the observable bug and the affected UI surfaces, and the evidence plus interface requirements pin down the exact hooks (new compose_pm_pill export, pm_list refresh) and the full matrix of cases (deactivate/reactivate \u00d7 human/bot), so two engineers would produce compatible implementations."
}
