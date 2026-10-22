# Include unsubscribed channels in the Move topic / Move messages channel selectors

## Background

In the Zulip web app, the **Move messages** and **Move topic** dialogs let a user pick a destination channel from a dropdown widget. Today, that dropdown is populated with **only the channels the acting user is subscribed to** (the same generic subscribed-channels option list used elsewhere in the app, built by `stream_data.get_options_for_dropdown_widget()`).

This is too restrictive: a user may legitimately want to move a topic or a set of messages to a channel they can access but are not subscribed to. The channel **mention typeahead** already handles this correctly — it offers all channels the user has content access to, listing unsubscribed channels below subscribed ones. The move-destination dropdowns should behave the same way.

## Required behavior

The channel dropdown in both the Move messages and Move topic dialogs must offer **every non-archived channel whose content the acting user can access**, not just subscribed channels. Concretely:

1. **Which channels appear.** A channel is included if and only if it is not archived and the user has content access to it under the app's existing content-access rules. That means, in addition to all of the user's subscribed channels, the list must include unsubscribed channels the user can access — for example public channels, web-public channels, and private channels that the user is permitted to join per the channel's group-based permission settings (e.g. the user belongs to the channel's `can_subscribe_group`). A channel must drop out of the list when the user loses content access to it (e.g. a public channel the user is not subscribed to becomes private and the user is not in any group granting access).
2. **Ordering.** Subscribed channels are listed first, followed by unsubscribed channels (mirroring the channel mention typeahead's grouping). Within each of the two groups, channels are sorted alphabetically by channel name, case-insensitively.
3. **Option shape.** Each entry in the dropdown's option list uses the pre-existing dropdown-widget option shape `{name, unique_id, stream}`, where `name` is the channel's name, `unique_id` is the channel's `stream_id`, and `stream` is the channel's full subscription object, passed through unmodified.

The existing generic subscribed-channels option list (`get_options_for_dropdown_widget()`) must keep its current behavior for its other call sites; the move dialogs get their own, broader list.

## Interface requirements

- The `stream_data` module must export a new function `get_streams_for_move_messages_widget()` (public within the web app; consumed by the move-topic/move-messages popover code) that returns the channel option list for the move-messages/move-topic destination dropdown.
- Each entry returned by `get_streams_for_move_messages_widget()` must be a dropdown-widget option of the pre-existing shape `{name, unique_id, stream}`: `name` is the channel's name, `unique_id` is its `stream_id`, and `stream` is the channel's full subscription object, unmodified.
- The returned list must include every non-archived channel whose content the user can access — not just subscribed channels. Unsubscribed channels are included when the user has content access (e.g. public channels, or private channels the user can subscribe to per the channel's group-based permission settings such as `can_subscribe_group`), and excluded when that access is lost.
- Ordering of the returned list: subscribed channels come before unsubscribed channels; within each group, channels are sorted alphabetically by name, case-insensitively.
- The Move messages and Move topic dialogs must populate their channel dropdown from this new function.

## Notes for implementation

- "Content access" should reuse the codebase's existing notion of channel content access (there are existing helpers in `stream_data` for evaluating access based on `invite_only`, `is_web_public`, subscription status, and the group-based permission fields like `can_subscribe_group`, `can_add_subscribers_group`, and `can_administer_channel_group`) rather than reimplementing the policy ad hoc.
- Archived channels must never appear in the list, regardless of subscription status or access.
- The result must reflect live channel state: changes to a channel's privacy, permission groups, subscription status, or archived flag must change subsequent results accordingly (i.e., compute the list from current data on each call rather than caching a stale snapshot).
