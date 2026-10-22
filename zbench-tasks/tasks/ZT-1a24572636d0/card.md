# ZT-1a24572636d0 -- pm_conversations: Remove empty DM conversations from the sidebar.

- lang: web   issue: #29275   tier: B
- fix: https://github.com/zulip/zulip/commit/1a24572636d0f1ff33603a3ba8cd055317ce0a72
- f2p: web/tests/dispatch.test.cjs, web/tests/echo.test.cjs, web/tests/message_store.test.cjs, web/tests/pm_conversations.test.cjs, web/tests/pm_conversations_util.test.cjs
- p2p: web/tests/pm_list_data.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned bug fix (empty DM conversations lingering in the left sidebar) with substantial cross-module logic changes. The hidden tests grade observable behavior deterministically: that deleting a DM triggers conversation removal logic with the right user_ids/counts, that un-cached deletions take no action, and that local echo messages are counted only on server ack. Assertions use stubs and small structured deepEquals on data-structure state, not long pinned strings or rendered snapshots, so a fail-before/pass-after signal is clean and not format-brittle."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "Conversation objects returned by `pm_conversations.recent.get()` gain an integer field `local_message_count`: a lower bound on messages locally known to remain in the conversation, initialized to 0 when a conversation is first inserted.",
    "`pm_conversations.process_message(message, is_server_message)` gains a second boolean parameter: true only for server-delivered (acked) messages; only those increment `local_message_count` (locally-echoed messages must not). Existing callers/tests pass the boolean explicitly.",
    "New exported method `pm_conversations.recent.increment_local_message_count(user_ids: number[])`: increments `local_message_count` for the conversation keyed by those user ids (the DM partners, excluding the current user).",
    "`echo.reify_message_id(local_id, server_id)`: when the acked message is a direct message, it must call `pm_conversations.recent.increment_local_message_count(user_ids)` exactly once, with user_ids = the DM recipients excluding the current user (from `people.pm_with_user_ids`), mirroring how stream messages are added to stream_topic_history only on ack.",
    "New exported method `pm_conversations.recent.maybe_remove(user_ids: number[], num_messages: number)`: if `local_message_count > num_messages`, decrement it by num_messages; otherwise remove the conversation from the recent-DMs data (subject to un-acked local-echo messages, tracked via echo_state's waiting-for-ack map, keeping it alive). No-op if the conversation is unknown.",
    "Handling of a server `delete_message` event with `message_type: \"private\"`: derive the conversation's user ids (excluding the current user's own id) from the deleted messages found in the local message cache, call `pm_conversations.recent.maybe_remove(user_ids, num_deleted)` exactly once, and call `pm_list.update_private_messages()` once to refresh the DM sidebar. If none of the deleted message ids are in the local cache, make no `maybe_remove` call.",
    "The delete handler and reify handler operate on `pm_conversations.recent` as the module-level singleton (tests stub its methods via `override(pm_conversations.recent, ...)`), so these methods must live on that exported object."
  ],
  "reason": "The tests do not touch pre-existing interfaces only: they stub and assert exact new method names (`maybe_remove`, `increment_local_message_count`), a new field (`local_message_count`) in `recent.get()` output, and a new boolean parameter on `process_message`. However, every bound name is exported, cross-module surface of `pm_conversations`/`echo` \u2014 the kind of inter-module API a Zulip design spec would legitimately dictate, especially since the feature explicitly mirrors the existing `stream_topic_history.maybe_remove`/`count` pattern already in the codebase. Call-count and argument assertions (user ids excluding self, num_messages, exactly-once sidebar refresh) express the intended behavior, not incidental internals. Given a brief enumerating the contract above, a solver would be graded on correctness rather than name-guessing, so this is specifiable rather than clean or coupled."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user-visible goal (emptied DM conversations should leave the sidebar immediately, like topics) and the evidence plus interface requirements pin down a determinate, checkable design: a per-conversation lower-bound counter incremented only on acked messages (with DM sends counted at reification), a maybe_remove decrement/remove operation guarded by echo_state's waiting-for-ack map, and delete_message event handling that derives the conversation from cached messages, calls maybe_remove once, refreshes the sidebar, and no-ops when no deleted ids are cached."
}
