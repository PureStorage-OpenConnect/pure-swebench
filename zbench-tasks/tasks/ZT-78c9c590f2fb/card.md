# ZT-78c9c590f2fb -- quote: Introduce quoting multiple messages.

- lang: web   issue: #37878   tier: B
- fix: https://github.com/zulip/zulip/commit/78c9c590f2fb0a4c1ddef4cb7b07f42aecbbbe3b
- f2p: web/tests/compose_reply.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Real feature work (multi-message quoting) with a deterministic hidden test: it exercises build_and_process_quote_assets_for_messages through mocked fetch success/error paths and asserts observable outputs (which content source is used per message), failing before the change and passing after. Assertions are targeted deepEquals on small structured values, not snapshot or exact-long-string pins, and no version/time gating or format bookkeeping is involved."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The compose_reply module exports a function `build_and_process_quote_assets_for_messages(message_ids, callback)`: given an array of message IDs (each present in the client message store), it prepares quoting content for those messages and invokes `callback` with an array of quote assets, one per message ID, in the same order as the input IDs.",
    "Each quote asset is an object with exactly two fields: `message` (the full message object from the message store for that ID) and `quote_content` (a string containing the raw Markdown to quote).",
    "To obtain raw Markdown, the function performs one batch fetch via the existing `message_fetch_raw_content.get_raw_content_for_messages` API; on success, each message's `quote_content` is the fetched raw content at the corresponding position, and this fetched value is used even for messages that already have a locally cached `raw_content`.",
    "If the batch fetch fails (error callback), each message's `quote_content` falls back to the message's locally cached `raw_content` when present; otherwise it is produced by converting the message's rendered HTML `content` to Markdown using the existing `compose_paste.paste_handler_converter`."
  ],
  "reason": "The test's mock targets (message_fetch_raw_content.get_raw_content_for_messages with its message_ids/on_success/on_error parameter shape, and compose_paste.paste_handler_converter) are pre-existing module interfaces at the base commit, not internals invented by the fix, so stubbing them is legitimate boundary control. The only new names the test depends on are the exported function build_and_process_quote_assets_for_messages and its {message, quote_content} callback payload \u2014 public module API surface a design brief would naturally pin down, along with the success/fallback semantics the test asserts. With those contract items in the brief, the test measures correctness of the quoting behavior rather than guessing of private implementation choices."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue alone is thin, but the interface requirements and expected-behavior evidence pin down a determinate, checkable outcome: an exported compose_reply function with an exact name, exact asset shape, batch-fetch-first semantics, and a specific two-tier fallback on fetch failure. Two engineers working from this brief would produce compatible implementations."
}
