# ZT-e3fe7d3bd6aa -- messages: Add jump to date picker.

- lang: web   issue: #23995   tier: B
- fix: https://github.com/zulip/zulip/commit/e3fe7d3bd6aa66177e71b9f149a63a5db305dd5a
- f2p: web/tests/message_fetch.test.cjs, web/tests/message_view.test.cjs, web/tests/timerender.test.cjs
- p2p: web/tests/message_list_data.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Real, assignable feature work (jump-to-date navigation) with substantial frontend logic changes. The hidden tests grade observable behavior deterministically: they assert that a 'date' anchor fetch includes the anchor_date API parameter, that missing anchor_date raises a specific error, and that fast_track_current_msg_list_to_anchor selects the correct message ID for in-range, before-range, unfetched, and future dates (including triggering server fetches when needed). These are outcome assertions on fixed timestamps, not snapshots or exact long-string pins; the one class-attribute tweak in timerender.test.cjs is a minor incidental assertion, not the grading core."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The message-fetch layer supports a new anchor value \"date\": fetch options accept an optional string field `anchor_date` (an ISO 8601 timestamp). When anchor is \"date\", the pre-existing `get_parameters_for_message_fetch_api` must copy `anchor_date` verbatim into the outgoing API request parameters as `anchor_date`.",
    "When a fetch is requested with anchor \"date\" but no `anchor_date` value, the client must log the error \"Missing anchor_date for date anchor fetch\" and omit `anchor_date` from the request parameters (proceeding otherwise).",
    "web/src/message_view gains an exported function `fast_track_current_msg_list_to_anchor(anchor, anchor_date?)` where `anchor` is a string such as \"date\" and `anchor_date` is an ISO 8601 timestamp, used to jump the current message list to a point in time.",
    "For anchor \"date\": if a message at or after the given date is already in the locally loaded current list, select the first such message with scroll-to behavior (select options then_scroll: true, from_scroll: false).",
    "For anchor \"date\": if the date precedes all loaded messages and the oldest history has already been fully fetched, select the oldest loaded message (same then_scroll/from_scroll options, no server fetch).",
    "For anchor \"date\": if the date falls outside the loaded range on a side that has not been fully fetched (older side without found_oldest, or newer side without found_newest), the feature must fetch from the server by delegating to the pre-existing `message_fetch.load_messages_around_anchor`, passing the anchor value (\"date\"), a completion callback, and a fresh MessageListData to be populated; once the fetch callback runs, select the message matching the anchor date with select options then_scroll: true, from_scroll: false, force_rerender: true.",
    "For anchor \"date\": if the date is in the future and the newest message has already been fetched (found_newest), select the newest loaded message without issuing any server fetch (select options then_scroll: true, from_scroll: false).",
    "Calling `fast_track_current_msg_list_to_anchor(\"date\")` without an anchor date must log the error \"Missing required argument anchor_date\" and perform no selection.",
    "The date text rendered by timerender's `render_date` gains the CSS class `date_row_text`, prepended to the existing classes (resulting class attribute \"date_row_text timerender-content timerender0\")."
  ],
  "reason": "Every new name the tests bind to is legitimate contract surface for a 'scroll to date' feature brief: an API request field (`anchor_date`) and anchor sentinel value (\"date\"), one new exported cross-module function (`fast_track_current_msg_list_to_anchor`) whose name, signature, and range/fetch semantics a spec would dictate, two operator-facing error strings, and one DOM CSS class for the new UI hook. The remaining bindings are pre-existing interfaces at the base commit: `get_parameters_for_message_fetch_api`, `load_messages_around_anchor` (the stub matches its existing positional signature), `select_id` and its options including `force_rerender`, `MessageListData`/`fetch_status`, and `message_lists.update_current_message_list`. The stub of `load_messages_around_anchor` is a module-boundary mock of a pre-existing exported function, and a brief can reasonably require delegating the server fetch to it, so the solver never has to guess author-invented internals. With the contract above supplied in the brief, the tests grade behavioral correctness rather than name recall."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives the product intent (clickable dates open a picker; picking a date jumps the current narrow to that date), and the expected-behavior evidence plus interface requirements pin down the exact contract: the message_fetch `anchor_date` parameter handling and error message, the exported fast_track_current_msg_list_to_anchor function with precise selection options for in-range, before-range/found_oldest, out-of-range-fetch, future/found_newest, and missing-argument cases, and the date_row_text class on rendered dates. Together these make the outcome determinate and checkable by two independent engineers."
}
