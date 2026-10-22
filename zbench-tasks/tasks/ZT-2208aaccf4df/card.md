# ZT-2208aaccf4df -- custom_emails: Add campaign_name to send_custom_email.

- lang: py   issue: #36442   tier: B
- fix: https://github.com/zulip/zulip/commit/2208aaccf4df80da298f4b75babd5049656c94aa
- f2p: zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_argument, zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_context, zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_doubled_arguments, zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_dry_run, zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_headers, zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_no_argument, zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_remote_server, zerver.tests.test_management_commands.TestSendCustomEmail.test_custom_email_duplicate_prevention_by_user, zerver.tests.test_management_commands.TestSendCustomEmail.test_custom_email_with_dry_run, zerver.tests.test_management_commands.TestSendCustomEmail.test_custom_marketing_email_duplicate_prevention_by_email
- p2p: zerver.tests.test_send_email

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real engineering workflow: replaces the template-hash-based dedup key for custom emails with an explicit required campaign_name, changing observable behavior (CLI argument, RealmAuditLog extra_data contents, and duplicate-send prevention semantics). The hidden tests grade outcomes deterministically \u2014 audit log entries contain campaign_name, duplicate sends are excluded by campaign, mail.outbox counts \u2014 rather than pinning snapshots or incidental formatting. Fails before, passes after."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The `send_custom_email` management command gains a required CLI flag `--campaign-name`: a unique string identifier for the email campaign (e.g. 'q4_2025_update'), used instead of the template-content hash to track and prevent duplicate sends.",
    "The `options` dict accepted by the existing `send_custom_email` and `send_custom_server_email` functions gains a required string key `campaign_name`, carrying the same campaign identifier (mirroring the CLI flag, as all other keys in that dict do).",
    "RealmAuditLog entries of event type CUSTOM_EMAIL_SENT record the campaign identifier in `extra_data` under the key `campaign_name` (replacing the previous `email_id` key that held a truncated SHA-256 of the template text); `extra_data` continues to include `email_subject`. Duplicate-send exclusion of recipients is keyed on this `campaign_name` value rather than the template hash."
  ],
  "reason": "The tests exercise only public/observable surface: the management-command CLI invocation via call_command, the pre-existing send_custom_email/send_custom_server_email entry points (whose options dict is the documented mirror of the CLI flags), mail.outbox, and persisted RealmAuditLog rows. The new bindings are the flag name `--campaign-name`, the options key `campaign_name`, and the audit-log extra_data key `campaign_name` \u2014 all names a ticket ('replace template-hash dedup with an explicit required campaign name, recorded in the audit log') would legitimately dictate. The extra_data key is persisted data whose predecessor (`email_id`) was already asserted by pre-existing tests, so it is established test/contract surface, not an invented internal. The tests do not touch the refactored internals (custom_email_sender's changed signature and dropped tuple return are never asserted directly), so with these three names in the brief the test grades correctness rather than name-guessing."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_argument",
    "zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_remote_server",
    "zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_headers",
    "zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_context",
    "zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_no_argument",
    "zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_doubled_arguments",
    "zerver.tests.test_email_notifications.TestCustomEmails.test_send_custom_email_dry_run",
    "zerver.tests.test_management_commands.TestSendCustomEmail.test_custom_email_with_dry_run",
    "zerver.tests.test_management_commands.TestSendCustomEmail.test_custom_email_duplicate_prevention_by_user",
    "zerver.tests.test_management_commands.TestSendCustomEmail.test_custom_marketing_email_duplicate_prevention_by_email"
  ],
  "reason": "The diff threads a new required campaign_name option through existing tests rather than adding new ones. In test_email_notifications.py, hunks at pre-change lines 29-247 fall inside seven TestCustomEmails methods (verified against Zulip source method boundaries: test_send_custom_email_argument at ~26, test_send_custom_email_remote_server at ~62, test_send_custom_email_headers at ~99, test_send_custom_email_context at ~119, test_send_custom_email_no_argument at ~163, test_send_custom_email_doubled_arguments at ~198, test_send_custom_email_dry_run at ~233). In test_management_commands.py, the hunks at lines 556/574 fall in TestSendCustomEmail.test_custom_email_with_dry_run, lines 595-635 in test_custom_email_duplicate_prevention_by_user (explicit in diff), and line 703 in test_custom_marketing_email_duplicate_prevention_by_email (spans ~673-792). The hashlib import removal is module-level, not a test target."
}

## screen: statement
{
  "sufficient": true,
  "why": "The interface requirements plus the expected-behavior evidence fully determine the observable outcome: a required --campaign-name flag / campaign_name options key threaded through send_custom_email and send_custom_server_email, audit-log extra_data keyed by campaign_name instead of the email_id template hash, and duplicate-recipient exclusion keyed on campaign_name. The thin issue body adds nothing needed; the brief states current vs. required behavior concretely enough for independent compatible implementations."
}
