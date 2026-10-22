# ZT-a028a6b9fd88 -- custom_emails: Prevent duplicate emails from send_custom_email command.

- lang: py   issue: #19529   tier: B
- fix: https://github.com/zulip/zulip/commit/a028a6b9fd880872ac4c89646fc77d3137fdf5b1
- f2p: zerver.tests.test_management_commands.TestSendCustomEmail.test_custom_email_duplicate_prevention_by_user, zerver.tests.test_management_commands.TestSendCustomEmail.test_custom_marketing_email_duplicate_prevention_by_email, zerver.tests.test_management_commands.TestSendCustomEmail.test_email_sending_failure_does_not_create_audit_log
- p2p: zerver.tests.test_send_email

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, plausibly-assigned engineering task (high-priority issue: prevent double-sending of custom emails) with a clear observable outcome: RealmAuditLog CUSTOM_EMAIL_SENT rows created on send, users excluded on re-send, and no log rows on dry-run or delivery failure. The hidden tests grade behavior deterministically \u2014 audit-log counts and contents, dedup by user ID and by case-insensitive email across realms, and failure-path suppression \u2014 all of which fail before the change and pass after. The only exact-string assertions are a one-line 'Excluded N users' message and a subject/hash check, which are short, deterministic, and directly tied to the changed behavior, not long snapshot pinning."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "A new audit log event type `CUSTOM_EMAIL_SENT` is added to `AuditLogEventType` in `zerver.models.realm_audit_logs`.",
    "Each successful (non-dry-run) custom email delivery to a user creates one RealmAuditLog row with event_type CUSTOM_EMAIL_SENT, modified_user set to the recipient, realm set to the recipient's realm, and acting_user None.",
    "The audit log's extra_data contains a string field `email_id`: the email template hash, i.e. the first 32 hex characters of the SHA-256 of the raw markdown template file contents (the same hash custom_email_sender already computes).",
    "The audit log's extra_data contains a string field `email_subject`: the resolved subject line of the sent email.",
    "On subsequent sends of the same template (same email_id), targeted sends (-u/-r) must exclude users who already have a CUSTOM_EMAIL_SENT audit log entry for that email_id, matched by user.",
    "Marketing sends (--marketing / distinct_email) must exclude recipients whose delivery email case-insensitively matches the delivery email of any user already logged for that email_id, in addition to the existing case-insensitive distinct-email dedup among current recipients.",
    "When one or more users are excluded as already-recipients, the command prints to stdout exactly once: 'Excluded {count} users who already received this email', and prints nothing else for a non-dry-run send.",
    "Dry-run mode must not create any CUSTOM_EMAIL_SENT audit log entries.",
    "If email delivery fails (EmailNotDeliveredError from the existing send path), no audit log entry is created for that recipient, so the user is retried on a future send."
  ],
  "reason": "The test binds only to new contract surface a ticket would dictate: a new audit-log event type name, two extra_data field names with their semantics, dedup behavior, an operator-facing stdout message, and dry-run/failure semantics. The hash format it asserts matches the pre-existing template-hash computation at the base commit, and its only mock target (send_immediate_email) and exception type pre-exist. No private helpers, invented internals, or implementation-only choices are pinned, so a solver given these requirements would be graded on correctness, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives the motivation, event type name/value, extra_data content, and the marketing-mode dedup subtlety; the expected-behavior evidence pins down the exact stdout message, extra_data field names (email_id as first-32-hex-chars of SHA-256 of the template file, email_subject), per-user vs case-insensitive-email exclusion semantics, dry-run and delivery-failure behavior; interface requirements were included and rephrased as product requirements. Together these determine a checkable, unambiguous outcome."
}
