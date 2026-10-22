# Support preparing quote content for multiple messages

## Background

Zulip's web client lets a user quote a single message in the compose box ("Quote message"). We want to enable quoting **multiple messages at once** — e.g. a user selects a set of messages and quotes them all into one compose draft. The groundwork for this feature is a mechanism in the compose-reply code that, given a set of message IDs, gathers everything needed to build the quoted output for each of them.

Today, the quoting logic in `web/src/compose_reply.ts` is built around a single message: it fetches that one message's raw Markdown source and inserts it into the compose box. There is no way to ask for quote-ready content for an arbitrary list of messages in a single operation.

## Required behavior

Add a function to the `compose_reply` module that prepares "quote assets" for a list of messages. It takes an array of message IDs (each ID refers to a message already present in the client-side message store) plus a callback, and it invokes the callback with an array of quote assets — **one per input ID, in the same order as the input array**.

Each quote asset is an object with exactly two fields:

- `message`: the full message object retrieved from the client message store for that ID.
- `quote_content`: a string containing the raw Markdown that should be quoted for that message.

### How `quote_content` is determined

1. **Primary path — batch server fetch.** The function makes **one** batched request for the raw Markdown of all the requested messages, using the existing `message_fetch_raw_content.get_raw_content_for_messages` API. On success, that API yields the raw content for each message in the same order as the requested IDs; each message's `quote_content` is the fetched value at its position. The freshly fetched value is authoritative: it must be used even for messages that already have a locally cached `raw_content` field (the server copy may be newer).
2. **Fallback path — fetch failure.** If the batch fetch fails (its error callback fires), the callback must still be invoked with a complete asset list, using local data per message:
   - If the message object has a locally cached `raw_content`, use it as `quote_content`.
   - Otherwise, derive Markdown from the message's rendered HTML (`message.content`) by running it through the existing HTML-to-Markdown converter `compose_paste.paste_handler_converter`.

In both paths the output array must line up positionally with the input ID array, and every asset must carry the corresponding message object from the message store.

## Interface requirements

- The `compose_reply` module exports a function `build_and_process_quote_assets_for_messages(message_ids, callback)`: given an array of message IDs (each present in the client message store), it prepares quoting content for those messages and invokes `callback` with an array of quote assets, one per message ID, in the same order as the input IDs.
- Each quote asset is an object with exactly two fields: `message` (the full message object from the message store for that ID) and `quote_content` (a string containing the raw Markdown to quote).
- To obtain raw Markdown, the function performs one batch fetch via the existing `message_fetch_raw_content.get_raw_content_for_messages` API; on success, each message's `quote_content` is the fetched raw content at the corresponding position, and this fetched value is used even for messages that already have a locally cached `raw_content`.
- If the batch fetch fails (error callback), each message's `quote_content` falls back to the message's locally cached `raw_content` when present; otherwise it is produced by converting the message's rendered HTML `content` to Markdown using the existing `compose_paste.paste_handler_converter`.

## Notes

- This function is intended as a reusable building block: later UI work (mouse selection of message ranges, non-contiguous selection for move/delete/quote) will call it, so keep it decoupled from any particular selection UI.
- Reuse the existing single-message quoting infrastructure (raw-content fetching, paste conversion) rather than duplicating it; refactor as needed so single-message quoting and this multi-message path share the same underlying fetch/convert logic.
