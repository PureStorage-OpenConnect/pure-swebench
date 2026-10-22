# Rename the channel settings "Not subscribed" tab to "Available"

## Background

Zulip's channel (stream) settings overlay has a left panel listing channels, with tabs that filter the list. Today the tabs include **Subscribed** and **Not subscribed**. The "Not subscribed" tab's state is reflected in the URL (the channels-settings hash contains a `notsubscribed` segment), and the left-panel filtering code passes around a params object (returned by `get_left_panel_params` in `web/src/stream_settings_ui`, and accepted by the exported `redraw_left_panel` function) containing a boolean flag `show_not_subscribed` alongside `input` (the search string), `show_subscribed`, and the sort order.

The purpose of this tab is to help users (especially admins) find channels they can join. "Not subscribed" describes the mechanics rather than the purpose, so the tab should be renamed to **Available**.

## Required changes

1. **Tab label:** In the channel settings left panel, rename the "Not subscribed" tab to "Available" (translated string). All user-facing text that refers to this tab/view (e.g. empty-list placeholder messages such as "No channels match your filter"-style text specific to this tab, tooltips, etc.) should be updated to say "available" rather than "not subscribed" where it refers to this tab.
2. **URL:** The URL segment for this tab changes from `notsubscribed` to `available` (e.g. `#channels/available/...` instead of `#channels/notsubscribed/...`). Navigating to the new URL opens the Available tab, and switching to the Available tab produces the new URL. Update any code that generates or parses this hash accordingly.
3. **Filter flag rename:** Rename the left-panel filter boolean from `show_not_subscribed` to `show_available` throughout the frontend (the params object produced by `get_left_panel_params` and consumed by `redraw_left_panel`, and anywhere else the flag flows). Filtering semantics for this flag are unchanged in substance: when `show_available` is true, the panel shows only channels the user is **not** subscribed to (rows for subscribed channels are rejected); when both `show_subscribed` and `show_available` are false, all channels are shown subject to the search filter. Search matching (case-insensitive, comma-separated multi-keyword, matching both channel names and descriptions), the active-row behavior, and the sort orders (`by-stream-name`, `by-subscriber-count`, `by-weekly-traffic`) must all continue to work identically with the renamed flag.
4. **Show only joinable channels:** The intent of the Available tab is to show just the channels the user is actually allowed to subscribe to. Unsubscribed channels that the user has no permission to join should not be presented as "available" in this tab.
5. **Help center:** Update the help documentation that describes the channel settings tabs (e.g. articles about browsing/joining channels) to use the new "Available" name and reflect the new behavior, updating any references or links that pointed at the old tab name.

## Interface requirements

- The channel-settings left panel's "Not subscribed" tab is replaced by an "Available" tab, and the boolean flag in the left-panel filter parameters (the params object accepted by `stream_settings_ui`'s exported `redraw_left_panel` / produced by `get_left_panel_params`) is renamed from `show_not_subscribed` to `show_available`; when true, the panel shows only channels the user is not subscribed to (subscribed channels are rejected).

## Acceptance criteria

- The channel settings left panel shows an "Available" tab where "Not subscribed" used to be, and its URL uses `available`.
- With the Available filter active, only channels the user is not subscribed to (and may join) are listed; subscribed channels never appear there.
- With no tab filter active, searching "Po" in a realm containing channels named Poland and Pomona lists both; searching "Denmark, Pol" lists Denmark and Poland; matching remains case-insensitive, handles names like "C++", and matches descriptions as well as names.
- All existing sort orders continue to work in combination with the renamed filter flag.
- Help center content reflects the new tab name.
