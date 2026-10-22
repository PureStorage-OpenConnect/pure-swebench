# ZT-00fe2236dad8 -- message_delete: Sort message_ids when sending delete_message event.

- lang: py   issue: #34324   tier: B
- fix: https://github.com/zulip/zulip/commit/00fe2236dad87e63dc701fc4e3728b6223144323
- f2p: zerver.tests.test_events.NormalActionsTest.test_do_delete_message_stream
- p2p: zerver.tests.test_message_delete

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior change (API guarantee)",
  "reason": "Real observable behavior change: the delete_message event's message_ids list is now sorted. The hidden test deterministically fails before (messages passed in reverse order would yield unsorted IDs) and passes after, asserting sorted order rather than an exact snapshot or incidental formatting. This is a plausible assigned engineering task with a clean outcome-based grader."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test exercises only pre-existing interfaces: do_delete_messages (existing action), the existing delete_message event, and its existing message_ids field, all present at the base commit. The only new thing asserted is the behavior under test itself \u2014 that message_ids in the emitted event is sorted \u2014 which is the user-visible outcome any correct fix must produce, not a name or internal choice the solver would have to guess. No new identifiers, helpers, or mock targets are introduced by the test."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_events.NormalActionsTest.test_do_delete_message_stream"
  ],
  "reason": "The diff modifies a single existing test method in NormalActionsTest: the hunk edits the message ordering and adds a sorted-order assertion in the test immediately preceding test_do_delete_message_stream_legacy, which is test_do_delete_message_stream (the non-legacy stream message deletion test, confirmed by is_legacy=False in the check). No new test methods are introduced."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the goal (server-side guarantee that message_ids in events are sorted, plus documenting it), and the expected-behavior evidence pins down a concrete checkable outcome: a multi-message delete performed with messages supplied in reverse order must yield a delete_message event whose message_ids list is in ascending order. Together these define a determinate, verifiable behavior covering both the delete_message and update_message event paths."
}
