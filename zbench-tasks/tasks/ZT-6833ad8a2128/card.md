# ZT-6833ad8a2128 -- user_groups: Send metadata access related events on remove subgroups.

- lang: py   issue: #33420   tier: B
- fix: https://github.com/zulip/zulip/commit/6833ad8a2128bd7a3ca5d59345e4a6288a4f14a2
- f2p: zerver.tests.test_events.NormalActionsTest.test_user_group_events, zerver.tests.test_user_groups.UserGroupTestCase.test_update_user_group_members_noop_case
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real real-time-sync bug: removing subgroups didn't send stream deletion events to users losing metadata access. The hidden test grades observable behavior deterministically \u2014 it asserts the number and schema of events emitted (check_stream_delete, check_user_group_remove_subgroups) rather than pinning exact payload strings or snapshots. Fails before the fix (1 event, no stream delete) and passes after; a plausible assigned engineering task."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test exercises the pre-existing public action remove_subgroups_from_user_group through the existing verify_action event harness and validates output with pre-existing event checkers (check_user_group_remove_subgroups, check_stream_delete) for established user-visible event types. It asserts behavior only: removing a subgroup emits a stream deletion event to users who lose metadata access, and an empty subgroup list is a no-op. No new names, internal helpers, mock targets, or implementation-specific structures are referenced, so any correct implementation passes."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_events.NormalActionsTest.test_user_group_events",
    "zerver.tests.test_user_groups.UserGroupTestCase.test_update_user_group_members_noop_case"
  ],
  "reason": "The two test_events.py hunks (replacing bare remove_subgroups_from_user_group cleanup calls with verify_action blocks checking user_group_remove_subgroups/stream_delete events) are both inside NormalActionsTest.test_user_group_events. The test_user_groups.py hunk adds remove_subgroups_from_user_group(test_group, [], ...) to the empty-list noop assertions in UserGroupTestCase.test_update_user_group_members_noop_case."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the two buggy code paths and the evidence pins down the observable contract: subgroup removal that revokes private-channel access must emit exactly the user-group remove_subgroups event followed by a stream delete event; the no-access-change case emits only the group event; empty-input remove_subgroups_from_user_group must be a query-free no-op; the symmetric gain path emits group event, stream create, then peer add. That is determinate and checkable."
}
