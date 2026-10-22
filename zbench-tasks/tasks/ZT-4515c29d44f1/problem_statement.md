# Left sidebar: "more topics" can be incorrectly hidden for recently subscribed streams

## Context

In the Zulip web app, the left sidebar's topic list for a stream shows a limited number of topics, plus a "more topics" affordance when the client cannot be sure it knows the stream's complete topic history. Whether that affordance is shown is driven by `topic_list.is_full_topic_history_available(stream_id)` (in `web/src/topic_list.ts`), which currently answers by consulting `stream_topic_history.is_complete_for_stream_id`. That check compares the stream's `first_message_id` against the oldest message in the browser's contiguous cache of all messages (`all_messages_data`): if the cache reaches back to (or before) the stream's first message and the newest messages have been fetched, it concludes the client has all topics for the stream.

## The bug

That comparison is only valid if the user has been continuously subscribed to the stream for the entire period covered by the cache. For a stream the user recently (re)subscribed to, the client's message cache may span the stream's full message-ID range **without actually containing the stream's older messages**, because those messages were never delivered to this client. In that situation the check wrongly concludes the full topic history is locally known, `is_full_topic_history_available` returns `true`, and the "more topics" option is incorrectly hidden — the user sees an incomplete topic list with no way to expand it.

There is no per-user value recording the first message sent to a stream after the user last (re)subscribed, so the cache-range comparison cannot be made trustworthy on its own. The chosen remedy is: when the cache-range heuristic *would* have claimed completeness, treat history as not yet known to be complete, and instead ask the server for the stream's full topic history. Once the server-fetched history is recorded, the existing mechanisms can treat the topic history as complete.

## Required behavior

Change the behavior of `topic_list.is_full_topic_history_available(stream_id)` as follows:

1. **Cases that already return `false` must be unchanged.** If the message cache is uninitialized/empty, has not found the newest messages, or does not reach back to the stream's `first_message_id`, the function still returns `false` (and should not trigger any server fetch in those cases).
2. **If the stream's topic history has already been confirmed complete from the server** (i.e., the full topic history was previously fetched and recorded via the existing `stream_topic_history` mechanisms), the function returns `true`.
3. **New behavior — cache range covers the stream but server has not confirmed completeness:** when the stream's `first_message_id` is covered by the locally cached message range (first cached message id ≤ `sub.first_message_id`) but the server has not yet confirmed the full topic history, the function must:
   - return `false`, so the "more topics" affordance remains visible rather than being hidden on the strength of the unreliable cache heuristic; and
   - synchronously, during that same call, initiate a server fetch of the stream's full topic history by calling the pre-existing `stream_topic_history_util.get_server_history`, passing the stream's id as the first argument (a callback that re-renders/updates the topic list widget when the data arrives is the natural second argument, so the sidebar updates once the fetch completes).

The net effect: instead of silently hiding "more topics" based on a heuristic that is wrong for recently subscribed streams, the client keeps the affordance visible and proactively fetches authoritative topic history from the server, after which the topic list reflects the true complete state.

## Interface requirements

- When a stream's `first_message_id` is covered by the locally cached message range (i.e. `sub.first_message_id >=` the first cached message id) but the server has not yet confirmed the full topic history, `topic_list.is_full_topic_history_available(stream_id)` must return `false` (keeping the "show all topics" affordance visible) instead of the previous behavior of returning `true`.
- In that same case, the function must immediately (synchronously, during the call) initiate a server fetch of the stream's full topic history by calling the pre-existing `stream_topic_history_util.get_server_history`, with the stream's id as the first argument.

## Notes for implementation

- `stream_topic_history_util.get_server_history` already exists and handles fetching and recording a stream's full topic history (it is a no-op if a fetch for that stream is already in flight or the history is already known); reuse it rather than adding a new fetch path.
- Be careful about module dependencies: `topic_list` is the appropriate place to trigger the fetch; avoid pushing the fetch into lower-level data modules like `stream_topic_history` itself.
- The extra server query is acceptable cost-wise: it only fires for streams whose topic list would otherwise show the (small) truncated set, and it is cheap when the stream has few topics.
