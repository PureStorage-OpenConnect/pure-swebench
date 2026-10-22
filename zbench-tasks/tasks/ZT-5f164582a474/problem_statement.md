# Allow customizing a channel's notification settings directly from Personal settings > Notifications

## Background

In the Zulip web app, **Personal settings > Notifications** contains a "Notification triggers" table that lists, one row per channel, the channels for which the user has assigned *custom* (non-default) notification settings. Each row shows the channel name on the left and a set of checkboxes for the per-channel notification settings, in this order: desktop notifications, audible (sound) notifications, mobile/push notifications, email notifications, and wildcard-mention notifications.

## Current behavior

The table only displays channels that *already* have custom notification settings. There is no way to add a new channel to this list from the Notifications settings page. To customize notifications for an additional channel, the user must leave this page and navigate to that channel's own settings (channel menu > personal tab), which is tedious.

## Required behavior

Make it possible to start customizing notifications for an additional channel directly from the Personal settings > Notifications table, by appending a special "customize another channel" row at the bottom of the stream-specific notification settings table:

1. **Left cell — channel picker.** The left cell of the new row is a channel dropdown listing only channels the user is subscribed to that currently use *default* notification settings (i.e., channels not already shown in the table). Muted channels must be included in this list. Before a selection is made, the dropdown shows the placeholder label "Customize another channel".
2. **Remaining cells — placeholder checkboxes.** The rest of the row contains the same five per-channel notification checkboxes as the other rows (desktop, audible, mobile/push, email, wildcard mentions). While no channel has been selected in the dropdown, all of these checkboxes are rendered **unchecked and disabled** — the user must not be able to interact with them.
3. **After selecting a channel.** Once the user picks a channel from the dropdown, that row becomes a normal editable row for the selected channel: its checkboxes become editable and behave exactly like the checkboxes of any other channel row (toggling them updates that channel's notification settings). A fresh "Customize another channel" placeholder row then appears below, so the user can repeat the process for further channels.
4. **Push notifications availability.** As elsewhere in this table, the mobile/push notifications checkbox must reflect whether push notifications are enabled for the realm: when the realm setting `realm_push_notifications_enabled` is false/unset, the push checkbox is in its "push notifications disabled" state (consistent with how existing rows handle this).

## Interface requirements

- `web/src/settings_config.ts` exports a new zero-argument function `get_custom_stream_specific_notifications_table_row_data()` that returns the checkbox row data for the 'customize a channel' placeholder row in the stream notification settings table.
- The return value is an array of the pre-existing `NotificationSettingCheckbox` objects (fields: `setting_name`, `is_checked`, `is_disabled`, `is_mobile_checkbox`, `push_notifications_disabled`), one per entry of the pre-existing `stream_specific_notification_settings` array, in that array's order (`desktop_notifications`, `audible_notifications`, `push_notifications`, `email_notifications`, `wildcard_mentions_notify`).
- In every row: `is_checked` is false and `is_disabled` is true (the placeholder row's checkboxes start unchecked and disabled until a channel is selected).
- `is_mobile_checkbox` is true only for the `push_notifications` row, false for all others.
- `push_notifications_disabled` is the boolean negation of `realm.realm_push_notifications_enabled` (true when the realm setting is unset/false).

## Notes for implementation

- "Channel" is the user-facing term for what much of the codebase still calls a "stream"; the relevant existing code lives around the stream-specific notification settings table (see `settings_config.ts`, the notification settings modules, and the corresponding Handlebars templates for the notifications table).
- The placeholder row's checkbox data must come from the exported function above so the rendering path for the placeholder row is driven by that data (unchecked, disabled, with the push-notifications state derived from the realm setting).
