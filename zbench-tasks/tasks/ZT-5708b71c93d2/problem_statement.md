# Add a channel-folder filter to the Recent Conversations view

## Background

Zulip's web app has a **Recent Conversations** view (`web/src/recent_view_ui.ts`, rendered with the `recent_view_filters` template and related templates). It currently offers filters such as a view-type dropdown, unread/participated/muted/DM toggles, and a "Filter topics" search input. Rows in the table are either channel (stream) topic conversations or direct-message (DM) conversations, and visibility is decided by the function `filters_should_hide_row(conversation)`.

Separately, the app already has **channel folders**: subscriptions carry a `folder_id` (a number, or `null` for channels not in any folder). The channel-settings overlay already has a folder filter built from two shared modules:

- `web/src/channel_folders` — includes `user_has_folders()` (whether the organization has any channel folders visible to the current user), `get_folders_with_accessible_channels()`, `is_valid_folder_id()`, and `get_channel_folder_by_id()`.
- `web/src/folder_dropdown_widget` — includes the `FOLDER_FILTERS` sentinel constants, notably `UNCATEGORIZED_DROPDOWN_OPTION` and `ANY_FOLDER_DROPDOWN_OPTION`, used alongside real folder ids as dropdown values.

Currently, Recent Conversations has no way to filter by folder.

## Required behavior

Add a folder filter to the Recent Conversations view, matching the one in channel settings:

### UI

- Add a folder-filter button immediately to the right of the view-type dropdown in the Recent Conversations filter bar.
- Use the same folder-chevron icon as the channel-settings folder filter, styled as an icon-style button.
- The button is neutral-colored when no folder filter is active (the "Any folder" default), and brand-colored when any folder filter is selected (a specific folder or "Uncategorized").
- Clicking the button opens a dropdown with the same options as the channel-settings folder filter: "Any folder" (default), each channel folder the user can see, and "Uncategorized" for channels not in any folder. Reuse the existing `folder_dropdown_widget` machinery rather than building a new dropdown.
- The button must only appear when the organization has channel folders visible to the user (i.e. when `channel_folders.user_has_folders()` is true). When there are no folders, the filter bar looks exactly as it does today.
- The minimum width of the "Filter topics" search input must remain unchanged; since the new button takes horizontal space, the search input will simply wrap onto a new line earlier than before.

### Filtering semantics

The folder filter participates in `filters_should_hide_row(conversation)` alongside the existing filters (all existing filter behavior is unchanged):

- **Default ("Any folder", the `FOLDER_FILTERS.ANY_FOLDER_DROPDOWN_OPTION` sentinel):** folder filtering hides nothing.
- **A specific folder id selected:** only channel-conversation rows whose channel's subscription has `folder_id` equal to that id are shown; channel rows in other folders or with no folder are hidden.
- **"Uncategorized" (the `FOLDER_FILTERS.UNCATEGORIZED_DROPDOWN_OPTION` sentinel):** only channel-conversation rows whose channel's subscription has `folder_id === null` are shown.
- **Any non-default selection (a concrete folder id or "Uncategorized"):** all direct-message conversation rows are hidden, regardless of other filter state.

The row's channel is determined from the conversation's last message (its `last_msg_id`), consistent with how other row properties are already derived.

### State handling

- The folder filter defaults to "Any folder" and resets to "Any folder" whenever the view's filters are cleared/reset, so that after a reset no row is hidden by folder filtering.

## Interface requirements

- `web/src/recent_view_ui.ts` must export a function `set_folder_filter_for_tests(value: number)` that sets the recent view's active folder filter to `value`, where `value` is either a channel-folder id or one of the existing `folder_dropdown_widget.FOLDER_FILTERS` sentinels.
- The existing exported `clear_for_tests()` in `recent_view_ui` must also reset the folder filter to its default, `FOLDER_FILTERS.ANY_FOLDER_DROPDOWN_OPTION` (the "Any folder" state), so that after a reset no row is hidden by folder filtering.
- The context object rendered into the `recent_view_filters` template gains a boolean field `show_folder_filter`, whose value is `channel_folders.user_has_folders()` — true only when the organization has channel folders visible to the user. The existing fields `filter_unread`, `filter_participated`, `filter_muted`, `filter_pm`, `search_val`, and `is_spectator` are unchanged.
- Folder-filter semantics of the existing `filters_should_hide_row(conversation)` must be exactly as described under "Filtering semantics" above: with the default `ANY_FOLDER_DROPDOWN_OPTION` sentinel active, folder filtering hides nothing; with any non-default folder filter active, all direct-message rows are hidden; with `UNCATEGORIZED_DROPDOWN_OPTION` active, only channel conversations whose subscription has `folder_id === null` are shown; with a concrete folder id active, only channel conversations whose subscription's `folder_id` equals that id are shown.
- The implementation must reuse the pre-existing shared modules rather than reimplementing them: `recent_view_ui` must import and consult `channel_folders` (for `user_has_folders()`) and `folder_dropdown_widget` (for the `FOLDER_FILTERS` sentinel constants) as part of this feature.
