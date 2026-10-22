# Notify users when their account is modified by someone else

## Background

Zulip administrators (and automated systems such as LDAP synchronization) can modify attributes of another user's account: their role, their full name, and their custom profile field values. Today these changes happen silently — the affected user receives no notification and may not realize their account was changed, by whom, or what the old and new values were.

## Required behavior

When a user's account is modified, the affected user must be notified via a direct message sent by the realm's Notification Bot informing them of the change.

### Message content

The notification message body must start with one of two opening sentences, depending on whether a specific person made the change:

- If the change was made by an identifiable person (e.g. an administrator acting through the UI or a management command run on their behalf), the message starts with a mention of that person, followed by the rest of the sentence:

  > {mention of the acting user} has made the following changes to your account.

  Use Zulip's existing silent-mention helper (`silent_mention_syntax_for_user`, in `zerver/lib/mention.py`) to build the mention — the same helper already used elsewhere in the codebase to reference a user without pinging them.

- If the change was made by the system itself, with no specific acting person (e.g. a bulk management command run with no `acting_user`, or an LDAP sync job), the message instead starts with:

  > The following changes have been made to your account.

Both variants end with the exact same period, and both are followed by, for each changed field, a pair of Markdown lines of the form:

```
- **Old <field label>:** <old value>
- **New <field label>:** <new value>
```

When an old or new value is empty (e.g. a custom profile field being cleared, or set for the first time), render it as `*None*` (italicized), not as an empty string.

Field labels:

- For the built-in name field, the label is `full name` (e.g. `**Old full name:** King Hamlet` / `**New full name:** New Name`).
- For a custom profile field, the label is that field's configured name as set by the realm administrator.

Custom profile field values must be rendered as human-readable display values matching the field's new state — for SELECT fields show the chosen option's text (not its internal option key), and for USER fields show user mentions, etc. Do not show raw internal representations.

When a single operation changes multiple fields at once (e.g. an LDAP sync run that updates several custom profile fields, or an admin editing several custom profile fields in one request), the affected user should receive one message covering all changed fields, with an Old/New line pair for each field. Between one field's New line and the next field's Old line, insert a line containing exactly `____`, followed by two blank lines (nothing follows the last field's New line).

### When to notify — and when not to

- Notify when someone *other than the user themself* changes the user's account (e.g. an administrator, or automated LDAP synchronization).
- Do **not** send a notification when the acting user is the affected user (self-changes).
- Do **not** send a notification when the affected account is a bot.
- Callers must also be able to suppress the notification explicitly (see interface requirements below).
- No notification should be sent when nothing actually changed (a no-op update).

### LDAP synchronization

LDAP sync updates (full name changes and custom profile field updates) must trigger these notifications for the affected user, subject to the same suppression rules above. LDAP sync runs with no specific acting person, so it uses the "system change" message variant above.

## Interface requirements

- `do_change_user_role` and `do_change_full_name` (both already take an `acting_user: UserProfile | None` parameter) must gain a new **required** boolean keyword parameter named `notify`: when `True`, the affected user is notified of the account change as described above; when `False`, no notification is sent.
- `do_update_user_custom_profile_data_if_changed` currently takes only `(user_profile, data)`. It must gain **two** new required parameters: `acting_user: UserProfile | None` and `notify: bool`, with the same meaning as above. `acting_user` is needed so the function can pick the correct message variant and apply the self-change/bot suppression rule.
- `check_remove_custom_profile_field_value` (already takes `acting_user`) must likewise gain a required `notify: bool` parameter, and must send the notification (for a field being cleared, with the new value rendered as `*None*`) when `notify` is `True`.
- Because `notify` (and, for `do_update_user_custom_profile_data_if_changed`, `acting_user`) are required with no default value, **every existing call site of these four functions anywhere in the codebase must be updated** to pass the new argument(s) explicitly with the appropriate value. This is a large, scattered change — expect call sites in management commands, views, LDAP/SCIM backends, `populate_db`, and test helper code, not only in the files most directly related to the feature. In particular, the shared test helpers `set_full_name`, `set_user_custom_profile_data`, and the role-setting helper in `zerver/lib/test_classes.py` (`ZulipTestCase`) call these functions internally and must be updated to pass `notify=False` (and, for the custom-profile-data helper, `acting_user=None`) — these are easy to miss because they are test infrastructure, not part of the feature itself, but dozens of other tests call through them and will fail with a missing-argument error if they are not updated.
- LDAP synchronization must invoke `do_change_full_name` with `notify=True` passed as a keyword argument, so name changes made by LDAP sync trigger the user notification. LDAP-driven custom profile field updates must likewise result in a notification (`notify=True`, `acting_user=None`).
- When notified, the affected user receives a direct message from the notification bot whose content starts with one of the two exact sentences described above (chosen based on whether `acting_user` is `None`), followed by the Old/New field lines.
- Custom profile field values in the notification are rendered as human-readable display values (e.g., for SELECT fields the option text, for USER fields user mentions), matching the value shown for the field's new state; empty values render as `*None*`.
- Even when `notify=True` is passed, no notification is sent when the acting user is the affected user (self-change) or when the affected profile is a bot.

## Notes

- The notification should be sent within the same operation/transaction flow as the change itself, so that immediately after the change completes, the most recent message received by the affected user is this notification.
- Existing behavior of these action functions (audit logging, events sent to clients, database updates) must be unchanged apart from the added notification.
