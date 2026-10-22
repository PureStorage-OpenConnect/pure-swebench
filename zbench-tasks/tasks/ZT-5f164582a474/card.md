# ZT-5f164582a474 -- settings: Add channel notifications customization in Personal settings.

- lang: web   issue: #19849   tier: B
- fix: https://github.com/zulip/zulip/commit/5f164582a474cfe0e2c9bc47fa56ac4169aa3750
- f2p: web/tests/settings_config.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Real, plausibly-assigned feature work (adding a 'customize a channel's notifications' row in Personal settings > Notifications) with substantive frontend logic. The hidden test calls the new settings_config helper and deepEqual-asserts a small structured array of checkbox row-config objects \u2014 deterministic, behavior-anchored data (setting names, disabled/checked flags, push-notification gating), matching the style of the existing all_notifications test in the same file. It fails before the change (function doesn't exist) and passes after; it is not an HTML/JSON snapshot or exact-string pin, so it grades outcome rather than incidental formatting."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "web/src/settings_config.ts exports a new zero-argument function `get_custom_stream_specific_notifications_table_row_data()` that returns the checkbox row data for the 'customize a channel' placeholder row in the stream notification settings table.",
    "The return value is an array of the pre-existing NotificationSettingCheckbox objects (fields: setting_name, is_checked, is_disabled, is_mobile_checkbox, push_notifications_disabled), one per entry of the pre-existing `stream_specific_notification_settings` array, in that array's order (desktop_notifications, audible_notifications, push_notifications, email_notifications, wildcard_mentions_notify).",
    "In every row: `is_checked` is false and `is_disabled` is true (the placeholder row's checkboxes start unchecked and disabled until a channel is selected).",
    "`is_mobile_checkbox` is true only for the `push_notifications` row, false for all others.",
    "`push_notifications_disabled` is the boolean negation of `realm.realm_push_notifications_enabled` (true in the test environment, where the realm setting is unset/false)."
  ],
  "reason": "The test binds to exactly one new name \u2014 an exported settings_config getter \u2014 plus its return contract, which reuses the pre-existing NotificationSettingCheckbox shape and the pre-existing stream_specific_notification_settings ordering. A brief stating the function name, signature, and the disabled/unchecked/mobile/push-disabled semantics fully determines the assertion, so the test grades correct behavior rather than name-guessing. It does not reach into private helpers, internal mocks, or the dropdown-widget internals of the fix."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the UX requirements concretely (dropdown contents, placeholder label, disabled checkboxes until selection, new placeholder row after selection), and the evidence plus interface requirements pin down the exact data contract for the placeholder row's checkbox state, so two engineers would build compatible implementations."
}
