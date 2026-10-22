# ZT-4515c29d44f1 -- topic_list: Fix missing 'show all topics' when messages not cached.

- lang: web   issue: #28949   tier: B
- fix: https://github.com/zulip/zulip/commit/4515c29d44f154ef2e9699af8a805a2075c82442
- f2p: web/tests/topic_list.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned frontend logic bug fix (missing 'show all topics' link when messages aren't cached). The hidden test grades observable behavior deterministically: is_full_topic_history_available now returns false in the uncached-topics case and triggers a server history fetch for the correct stream_id, verified via a mocked get_server_history. It fails before the fix and passes after, with no exact-string, snapshot, version, or time-based assertions."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When a stream's `first_message_id` is covered by the locally cached message range (i.e. `sub.first_message_id >= first cached message id`) but the server has not yet confirmed the full topic history, `topic_list.is_full_topic_history_available(stream_id)` must return false (keeping the 'show all topics' affordance visible) instead of the previous behavior of returning true.",
    "In that same case, the function must immediately (synchronously, during the call) initiate a server fetch of the stream's full topic history by calling the pre-existing `stream_topic_history_util.get_server_history`, passing the stream's id as the first argument."
  ],
  "reason": "The test exercises the pre-existing exported function `topic_list.is_full_topic_history_available` and asserts a behavior change (returns false where it used to return true) plus that a server fetch is triggered. The only stub target is `stream_topic_history_util.get_server_history`, which already exists at the base commit as the codebase's canonical exported utility for fetching a stream's topic history \u2014 a ticket could legitimately dictate 'fetch full topic history via the existing stream_topic_history_util.get_server_history', so this is contract surface, not an invented internal. The test does not bind to any of the fix's genuinely internal choices: it never references the new `num_topics_displayed` parameter (it calls with one argument, which JavaScript permits), the new private helper `update_widget_for_stream`, the callback's rebuild logic, or the blueslip warning text. With the two contract items above in the brief, the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue explains the root cause and the intended direction (fetch full topic history instead of trusting the cache-range heuristic), and the evidence plus interface requirements pin down the exact observable behavior: return false and synchronously call stream_topic_history_util.get_server_history(stream_id) in the previously-true case. This is a determinate, checkable outcome."
}
