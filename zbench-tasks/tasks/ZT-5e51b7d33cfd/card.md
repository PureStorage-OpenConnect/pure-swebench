# ZT-5e51b7d33cfd -- notifications: Send private messages for user profile modifications.

> **HELD (2026-08-17), quarantined out of the 123-task validated corpus.** Oracle-valid
> and not a brief-clarity problem (see the 2026-08-17 note on the coupling screen below) --
> the required-parameter migration touches ~15 scattered call sites, and 8/8 completed
> re-attempts across 8 different model/harness combos on the fixed brief still failed on
> the same missed call site. Revisit as a possible split/simplify candidate; re-promote
> `curation_status` to `validated` in meta.json if resolved. See `zbench-tasks/corpus.py
> --status held` to list quarantined tasks.

- lang: py   issue: #23641   tier: B
- fix: https://github.com/zulip/zulip/commit/5e51b7d33cfd2b2ccaac4bd34df6ed73c2e719f7
- f2p: zerver.tests.test_management_commands.TestUserChangeNotifications.test_bulk_change_user_name_sends_notifications, zerver.tests.test_management_commands.TestUserChangeNotifications.test_change_user_role_sends_notifications, zerver.tests.test_users.PermissionTest.test_change_regular_member_to_guest, zerver.tests.test_users.PermissionTest.test_non_admin_cannot_change_full_name
- p2p: zerver.tests.test_message_send, zerver.tests.test_scim

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, plausibly-assigned feature (notify users via Notification Bot PM when their profile is modified by someone else / LDAP sync) with a clear observable outcome: a message is sent to the affected user. The hidden tests grade behavior deterministically \u2014 they fetch the most recent message and use targeted assertIn checks on key phrases, not an exact full-string or snapshot pin (except one assertEqual on a single-field delete case). Remaining test churn (adding notify=False to existing do_change_user_role/do_change_full_name call sites) reflects the API change itself, not incidental formatting."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "do_change_user_role and do_change_full_name (both already take acting_user: UserProfile | None) gain a new required boolean keyword parameter `notify`: when true, the affected user is notified of the account change; when false, no notification is sent.",
    "do_update_user_custom_profile_data_if_changed currently takes only (user_profile, data); it must gain two new required parameters, `acting_user: UserProfile | None` and `notify: bool`. check_remove_custom_profile_field_value (already takes acting_user) must likewise gain a required `notify: bool`.",
    "Because notify (and, for do_update_user_custom_profile_data_if_changed, acting_user) are required with no default, every existing call site of these four functions must be updated \u2014 including the shared test helpers set_full_name, set_user_custom_profile_data, and the role-setting helper in zerver/lib/test_classes.py's ZulipTestCase.",
    "LDAP synchronization must invoke do_change_full_name with `notify=True` passed as a keyword argument; LDAP-driven custom profile field updates must likewise notify with acting_user=None.",
    "The message body starts with one of two exact sentences depending on whether acting_user is None: '{mention of the acting user} has made the following changes to your account.' (built with the existing silent_mention_syntax_for_user helper) when a specific person made the change, or 'The following changes have been made to your account.' when the system made the change.",
    "For each changed field, the notification message contains a Markdown line of the form '- **Old <field label>:** <old value>' and '- **New <field label>:** <new value>'; for the built-in name field the label is 'full name', and for custom profile fields the label is the field's configured name. Between fields, insert a line containing exactly '____' followed by two blank lines. An empty old or new value renders as '*None*'.",
    "Custom profile field values in the notification are rendered as human-readable display values (e.g., for SELECT fields the option text, for USER fields user mentions), matching the value shown for the field's new state.",
    "No notification is sent when the user changes their own profile (acting_user is the same user) or when the affected profile is a bot; callers may also suppress it explicitly with notify=False."
  ],
  "reason": "The test binds only to (a) a new `notify` boolean parameter on pre-existing, widely-used action-layer functions plus a new `acting_user` parameter on one of them, (b) user-visible notification message wording and formatting (now fully enumerated, including the acting-user-mention variant, the *None* empty-value rendering, and the ____ multi-field separator, all confirmed against the gold diff and the hidden test's literal assertions), and (c) delivery of that notification as a DM \u2014 all contract surface a ticket would legitimately dictate. The fix's internal helpers (send_user_profile_update_notification, get_custom_profile_field_display_value, UserProfileChangeDict) are never referenced by the tests. 2026-08-17 update: the smoke run showed 0/10 models producing the acting-user-mention sentence variant, because the brief previously quoted only the system-change sentence \u2014 required_contract above was rewritten to cover both variants and the two newly-required parameters explicitly."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product intent (Notification Bot DMs the user when an admin modifies their account), and the expected-behavior evidence pins down the concrete observable contract: required `notify`/`acting_user` keywords on the four action functions, LDAP sync passing notify=True, both exact notification sentence variants, the `- **Old <label>:**` / `- **New <label>:**` line format, the `____` field separator, the `*None*` empty-value rendering, the 'full name' label, human-readable custom-field values, and multi-field changes combined into one message. Together these are determinate and checkable. The issue's proposed 'Manual changes'/'Automated changes' template was evidently not adopted verbatim, so the brief specifies the observed message format instead."
}
