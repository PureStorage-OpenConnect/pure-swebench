# Guarantee that `message_ids` in server events are sorted

## Background

Zulip's real-time events system sends several event types that carry a batch of message IDs in a `message_ids` field:

- The `delete_message` event, sent when a batch of messages is deleted (when the batch contains more than one message, the event carries a `message_ids` list rather than a single `message_id`).
- The `update_message` event, sent when messages are edited or moved; when a topic/channel move affects multiple messages, the event's `message_ids` field lists every affected message.

Currently the server offers no guarantee about the ordering of these lists: the IDs appear in whatever order the internal code assembled them (e.g., the order the `Message` objects were passed to the deletion code path), which is not necessarily sorted. As a result, clients that need ordered IDs (for example, to efficiently apply message moves or deletions to locally cached message lists) must each sort the list themselves. The web app already does this client-side, and other official clients are about to duplicate that work.

## Required behavior

Make sorted order a server-side guarantee:

1. In every event the server sends that includes a `message_ids` field — in particular the `delete_message` event and the `update_message` event — the list of message IDs must be sorted in ascending numerical order. This must hold regardless of the order in which the affected messages were collected or passed into the code that builds the event. For example, if a bulk-delete operation is invoked with two messages provided in reverse ID order, the resulting `delete_message` event delivered to clients must still list the IDs in ascending order.
2. The sorting must be applied where the event payload is constructed on the server, so the guarantee holds for all clients and all code paths that trigger these events (deletion of multiple messages, topic edits/moves affecting multiple messages, etc.).
3. Update the API documentation (the event descriptions in Zulip's API/OpenAPI documentation for these events) to state explicitly that `message_ids` is sorted in ascending order, so clients can rely on it. Since this is a newly documented guarantee, record it in the API changelog with a corresponding API feature level entry, following the project's usual conventions for documenting API changes.

No change to the field name, type, or the set of events carrying it is desired — only the ordering guarantee and its documentation.

## Acceptance criteria

- Deleting multiple messages in one operation produces a `delete_message` event whose `message_ids` list equals the same list sorted ascending, even when the messages were supplied to the deletion operation in unsorted (e.g., reverse) order.
- `update_message` events produced by moves/edits affecting multiple messages likewise carry `message_ids` in ascending order.
- The API documentation for the affected events describes the sorted-order guarantee, and the API changelog notes when the guarantee was introduced.
