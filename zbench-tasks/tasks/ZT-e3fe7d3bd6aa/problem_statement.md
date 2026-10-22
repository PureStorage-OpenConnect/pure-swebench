# Jump to date: let users navigate the message view to a specific point in time

## Background

Zulip's web client renders dates in two places within a message feed: the sticky message header bar (recipient bar area) and the date separator rows between messages from different days. Today these date displays are inert text. Users who want to scroll back to what was said on a particular day have no direct way to get there — they must scroll manually or construct a `near:` search.

This task adds a "jump to date" capability: clicking a date in the message feed opens a date picker, and choosing a date jumps the current view to the start of that date. The narrow (the current filter/view) must not change — only the scroll position / selected message within it.

## Product behavior

1. **Clickable dates.** Dates shown in the message header bar and on date separator lines become interactive. Clicking one opens a date selector (calendar picker). The picker should also offer convenient shortcuts, at minimum an option to jump to the very beginning of the conversation ("Jump to beginning" / oldest message; exact wording is flexible). A richer shortcut menu (e.g. "Oldest message", "Yesterday", "Newest message", "Custom…" opening the calendar) is welcome but the core requirement is: pick a date → the view jumps there.
2. **Jump semantics.** When the user selects a date, the view scrolls to and selects the first message sent at or after the start of that date, within the same narrow. If there are no messages on that exact date, land on the next message after it.
3. **Server fetch when needed.** The target date may fall outside the range of messages currently loaded in the client. In that case, the client must ask the server for messages around that date rather than failing or landing on a wrong message. This requires extending the message-fetch API layer with a date-based anchor (see below); the server API already understands an `anchor` of `"date"` accompanied by an `anchor_date` parameter.
4. **Edge behavior.**
   - Date earlier than all history, and history already fully loaded on the old end: land on the oldest message (no server round trip).
   - Date in the future, and the newest message already loaded: land on the newest message (no server round trip).

## Interface requirements

The implementation must expose the following exact names and semantics:

- **Message-fetch layer, new anchor value `"date"`.** The fetch-options object accepted by the message-fetch module gains an optional string field `anchor_date` holding an ISO 8601 timestamp (e.g. `"2024-01-02T00:00:00.000Z"`). The pre-existing function `get_parameters_for_message_fetch_api` in `web/src/message_fetch` must, when the fetch's anchor is `"date"`, copy the provided `anchor_date` verbatim into the outgoing API request parameters under the key `anchor_date`.
- **Missing date on a date-anchored fetch.** If a fetch is requested with anchor `"date"` but no `anchor_date` value, the client must log an error with the exact message `Missing anchor_date for date anchor fetch` (via the client's standard error-logging facility, blueslip) and build the request parameters without an `anchor_date` field, proceeding otherwise as normal.
- **`web/src/message_view` exports a new function `fast_track_current_msg_list_to_anchor(anchor, anchor_date?)`**, where `anchor` is a string such as `"date"` and `anchor_date` is an ISO 8601 timestamp string. It jumps the *current* message list to the point in time given by `anchor_date`, with this behavior for anchor `"date"`:
  - If a message whose timestamp is at or after the given date is already present in the locally loaded current list, select the first such message with select options `{then_scroll: true, from_scroll: false}` (no server fetch).
  - If the given date precedes every loaded message and the list's fetch status says the oldest history has already been fully fetched (`found_oldest`), select the oldest loaded message with the same options `{then_scroll: true, from_scroll: false}` and do not contact the server.
  - If the date falls outside the loaded range on a side that has *not* been fully fetched (older than the loaded range without `found_oldest`, or newer without `found_newest`), delegate to the pre-existing `message_fetch.load_messages_around_anchor`, passing the anchor value (`"date"`), a completion callback, and a *fresh* `MessageListData` for the fetch to populate (the fetch layer must be threaded so the date reaches the API request as described above). When the fetch completes and the callback runs, the current message list is updated with the fetched data and the message matching the anchor date is selected with options `{then_scroll: true, from_scroll: false, force_rerender: true}`.
  - If the date is in the future and the newest message is already loaded (`found_newest`), select the newest loaded message with `{then_scroll: true, from_scroll: false}` and issue no server fetch.
  - If called with anchor `"date"` but no `anchor_date` argument, log an error with the exact message `Missing required argument anchor_date` and select nothing (no state change).
- **Date text styling hook.** The date text produced by `render_date` in `web/src/timerender` must gain the CSS class `date_row_text`, *prepended* to its existing classes — i.e. a date element that previously had the class attribute `timerender-content timerender0` now has `date_row_text timerender-content timerender0`. This class is the hook for making rendered dates look and behave like clickable elements.

## Implementation notes / constraints

- The narrow must remain unchanged when jumping; only the anchor within the current view moves. Do not rewrite the search bar or the URL narrow terms as part of this task (adding e.g. `date:` operators to search is explicitly out of scope).
- Selection semantics: "select" means the message list's `select_id` with the option objects specified above; "first message at or after the date" is by message timestamp compared against the given ISO timestamp.
- The UI entry point (click handler on header-bar dates and date separator rows, and the picker itself) should reuse Zulip's existing date/calendar picker component (as used for scheduled messages) where practical, and ultimately call `fast_track_current_msg_list_to_anchor("date", <ISO timestamp of the selected day's start>)`.
