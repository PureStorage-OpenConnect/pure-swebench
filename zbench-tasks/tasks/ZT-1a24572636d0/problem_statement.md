# Remove empty DM conversations from the left sidebar when their messages are deleted

## Background

In the Zulip web app, the left sidebar shows a list of recent direct message (DM) conversations, backed by the recent-conversations data in `web/src/pm_conversations.ts` and rendered via `web/src/pm_list.ts`.

**Current behavior:** when all messages in a DM conversation are deleted (e.g., via server `delete_message` events), the conversation row remains in the left sidebar until the page is reloaded. Only after a reload does the emptied conversation disappear. This is inconsistent with stream topics, which are removed from the sidebar immediately when their last message is deleted.

**Required behavior:** when the web app learns that DM messages were deleted and can determine that a conversation has (as far as it knows) no messages left, it must remove that conversation from the recent-DMs data and refresh the DM section of the left sidebar immediately, without a reload.

## The core difficulty

The client cannot generally know how many messages a DM conversation contains — its message cache is partial. The design to implement is a conservative **lower bound** counter per conversation:

- Each recent-DM conversation tracks `local_message_count`: the number of messages the client has locally confirmed to exist in that conversation (a lower bound on the true count).
- The counter is incremented only for **server-acknowledged** messages. Locally-echoed (not yet acked) messages must not increment it when first processed; instead, the increment happens at the moment the local echo is reified with its real server id (`echo.reify_message_id`). This mirrors how stream messages are only added to `stream_topic_history` on ack, and prevents double counting: an echoed message would otherwise be counted once at echo time and again when the server event for it arrives.
- On deletion of N messages from a conversation: if `local_message_count > N`, we know messages remain, so just decrement by N. Otherwise the conversation is, as far as we know, empty — remove it from the recent-DMs data, **unless** there are still un-acked locally-echoed messages outstanding for that conversation (tracked in `echo_state`'s waiting-for-ack map), in which case keep it.

## Detailed requirements

### `pm_conversations` data model

- Conversation entries in the recent-DMs data structure (the objects returned by `pm_conversations.recent.get()`) carry an integer `local_message_count`, initialized to `0` when a conversation is first inserted. All other existing fields (`user_ids_string`, `max_message_id`) and the recency ordering behavior are unchanged.
- `pm_conversations.process_message(message, is_server_message)` takes a new second boolean parameter. When `is_server_message` is true (the message came from the server / is acked), processing the message increments the conversation's `local_message_count`; when false (local echo), it does not. All call sites must pass this flag explicitly. The existing early-return for non-DM / invalid messages is preserved (e.g., a message that is rejected before partner processing must not touch the counter).

### Counting acked sends

- When `echo.reify_message_id(local_id, server_id)` reifies a locally-echoed **direct** message, it must increment the count for that conversation exactly once, keyed by the DM recipients excluding the current user (as computed by `people.pm_with_user_ids`). Example: if the current user (id 123) sends a DM to user 21, reification results in exactly one increment for `user_ids = [21]`. Stream messages are unaffected.

### Deletion handling

- When the client processes a server `delete_message` event whose `message_type` is `"private"`:
  1. Look up the deleted message ids in the local message cache (`message_store`) to identify the conversation. Derive the conversation key as the message participants' user ids **excluding the current user's own id** (e.g., for a 1:1 DM between user 4 and the current user 20, the key is `[4]`).
  2. Call the removal logic once for that conversation with the number of deleted messages, then call `pm_list.update_private_messages()` once so the sidebar re-renders.
  3. If **none** of the deleted ids are present in the local cache, the conversation cannot be identified: perform no DM-conversation removal call. (Whether the sidebar refresh still happens in that case is your choice; the removal call must not happen.)
- Removal semantics: given the conversation's user ids and `num_messages` deleted — if the conversation is unknown, do nothing. If `local_message_count > num_messages`, decrement it by `num_messages`. Otherwise, remove the conversation from the recent-DMs data so it no longer appears in `pm_conversations.recent.get()` or the sidebar — except that if `echo_state`'s waiting-for-ack map shows outstanding un-acked local-echo messages for this conversation, it must be kept alive (not removed).
- Existing `delete_message` handling for stream messages (unread processing, emoji-frequency updates, message removal, stream topic removal) must continue to work unchanged.

## Interface requirements

- Conversation objects returned by `pm_conversations.recent.get()` gain an integer field `local_message_count`: a lower bound on messages locally known to remain in the conversation, initialized to 0 when a conversation is first inserted.
- `pm_conversations.process_message(message, is_server_message)` gains a second boolean parameter: true only for server-delivered (acked) messages; only those increment `local_message_count` (locally-echoed messages must not). Existing callers pass the boolean explicitly.
- New exported method `pm_conversations.recent.increment_local_message_count(user_ids: number[])`: increments `local_message_count` for the conversation keyed by those user ids (the DM partners, excluding the current user).
- `echo.reify_message_id(local_id, server_id)`: when the acked message is a direct message, it must call `pm_conversations.recent.increment_local_message_count(user_ids)` exactly once, with `user_ids` = the DM recipients excluding the current user (from `people.pm_with_user_ids`), mirroring how stream messages are added to stream_topic_history only on ack.
- New exported method `pm_conversations.recent.maybe_remove(user_ids: number[], num_messages: number)`: if `local_message_count > num_messages`, decrement it by `num_messages`; otherwise remove the conversation from the recent-DMs data (subject to un-acked local-echo messages, tracked via `echo_state`'s waiting-for-ack map, keeping it alive). No-op if the conversation is unknown. Removal is **optimistic**: whenever `maybe_remove` removes a conversation it must also invoke an injected reconfirmation hook `update_dm_last_message_id(user_ids)` (registered as described below) so the client can re-query the server and re-add the conversation if messages in fact remain.
- Handling of a server `delete_message` event with `message_type: "private"`: derive the conversation's user ids (excluding the current user's own id) from the deleted messages found in the local message cache, call `pm_conversations.recent.maybe_remove(user_ids, num_deleted)` exactly once, and call `pm_list.update_private_messages()` once to refresh the DM sidebar. If none of the deleted message ids are in the local cache, make no `maybe_remove` call.
- The delete handler and reify handler must operate on `pm_conversations.recent` as the module-level exported singleton object — `increment_local_message_count` and `maybe_remove` must live as methods on that exported `recent` object itself, and callers must invoke them through it (e.g., `pm_conversations.recent.maybe_remove(...)`), not via separately-exported free functions.
- The reconfirmation hook is injected, not imported directly: `pm_conversations` exposes `set_update_dm_last_message_id(fn)` to register it, and `maybe_remove` calls the registered `fn(user_ids)` when it removes a conversation. Also expose a public `pm_conversations.recent.remove(user_ids)` method that performs the actual removal from the recent-DMs data.
- New module `web/src/pm_conversations_util.ts` exporting `update_dm_last_message_id(user_ids, update_dom_on_success?)`: it queries the server for the most recent message in that DM narrow (via `message_util.get_last_message_id_in_narrow`, i.e. a `channel.get` to `/json/messages` with a `dm` operator anchored to the newest message). If a message is found it re-inserts the conversation (`pm_conversations.recent.insert(user_ids, last_message_id)`) and then calls `update_dom_on_success()` to refresh the sidebar. This module is wired to `pm_conversations.set_update_dm_last_message_id` during app initialization.

## Notes

- The counter is intentionally a lower bound: if `local_message_count` never exceeded the number of deletions (e.g., the client never counted any messages for that conversation), the conservative outcome is removal — matching the reload behavior, where an emptied conversation disappears. Because removal triggers the server reconfirmation described above, an over-eager removal is self-correcting: if the server reports that messages still exist, the conversation is re-added.
- Keep the recent-DMs persistence/rehydration path (if any) consistent with the new field so entries restored from stored state also have a well-defined `local_message_count`.
