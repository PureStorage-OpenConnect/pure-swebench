# Track custom email sends to prevent double-sending

## Background

Zulip server administrators can send one-off emails to portions of the userbase with `manage.py send_custom_email` (implemented in `zerver/management/commands/send_custom_email.py`, on top of `custom_email_sender` / `send_custom_email` in `zerver/lib/send_email.py`). The command accepts a Markdown template via `--path`, and selects recipients via `-u`/`--users` (comma-separated delivery emails), `-r`/`--realm`, or `--marketing` (all marketing-email-eligible users, deduplicated case-insensitively by delivery email so an address with accounts on multiple realms gets only one email).

Each custom email already has a stable identifier: the sending code computes a hash of the raw Markdown template file — the first 32 hex characters of the SHA-256 of the file's contents — and uses it in the generated template names.

**Problem:** if the job crashes partway through a large send, there is no convenient way to resume. Re-running the command emails everyone again, including users who already received the email. The only workaround today is string-parsing `/var/log/zulip/send_email.log`. Delivery state should instead be tracked in the database and used to automatically skip users who already got a given email.

## Required behavior

### 1. Record each successful delivery in RealmAuditLog

- Add a new audit log event type `CUSTOM_EMAIL_SENT` to `AuditLogEventType` in `zerver/models/realm_audit_logs.py`. Use the numeric value `800` (a new block, chosen not to conflict with the existing 700-range group).
- Every time a custom email is actually delivered to a user (i.e. a real, non-dry-run send), create exactly one `RealmAuditLog` row for that user with:
  - `event_type` = `CUSTOM_EMAIL_SENT`
  - `modified_user` = the recipient's `UserProfile`
  - `realm` = the recipient's realm
  - `acting_user` = `None`
  - `extra_data` containing:
    - `"email_id"` (string): the email's template hash — the first 32 hex characters of the SHA-256 hexdigest of the raw Markdown template file contents, identical to the hash the sending code already computes for the template.
    - `"email_subject"` (string): the resolved subject line of the email as sent.
- The row must be created only **after** delivery succeeds. If sending raises `EmailNotDeliveredError` (the existing failure path in `zerver/lib/send_email.py`, which the per-recipient loop already suppresses), no audit log row may be created for that recipient — so a failed recipient will be retried on a future run.
- Dry-run mode (`--dry-run`) must not create any `CUSTOM_EMAIL_SENT` rows.

### 2. Exclude users who already received the email

When the command runs, before sending, it must exclude recipients who already have a `CUSTOM_EMAIL_SENT` audit log entry whose `extra_data["email_id"]` equals the current template's hash:

- **Targeted sends** (`-u` / `-r`): exclude any selected `UserProfile` that itself has such an entry (matched by user).
- **Marketing sends** (`--marketing`, and generally any mode using the distinct-email dedup): exclusion must be by **delivery email, case-insensitively**, not by user ID. A candidate recipient must be excluded if *any* `UserProfile` already logged for this `email_id` has a delivery email that matches the candidate's delivery email case-insensitively. This preserves the marketing-mode guarantee that a given email address is only ever emailed once, even when the address has multiple accounts across realms (possibly with different capitalization). The existing case-insensitive distinct-by-delivery-email dedup among the current run's recipients must continue to work as before.

Example: user `DUPLICATE@example.com` has accounts on two realms. A `--marketing` run sends that address one email and logs one `CUSTOM_EMAIL_SENT` row (for whichever account was chosen). A second `--marketing` run with the same template sends that address nothing and creates no new row for either account.

Example: a run with `-u=iago@zulip.com,prospero@zulip.com` sends 2 emails and creates 2 audit rows. A follow-up run with `-u=iago@zulip.com,prospero@zulip.com,othello@zulip.com` and the same template sends only to Othello and creates exactly one new row (for Othello).

### 3. Reporting exclusions

- When one or more recipients are excluded because they already received this email, the command must print to stdout exactly one line, exactly:

  ```
  Excluded {count} users who already received this email
  ```

  where `{count}` is the number of excluded recipients.
- Apart from this line, a non-dry-run send must print nothing else to stdout. (Dry-run output, which prints the would-be recipients and a pointer to the generated preview file, is unchanged.)

## Interface requirements

- A new audit log event type `CUSTOM_EMAIL_SENT` is added to `AuditLogEventType` in `zerver.models.realm_audit_logs` (value 800).
- Each successful (non-dry-run) custom email delivery to a user creates one `RealmAuditLog` row with `event_type=CUSTOM_EMAIL_SENT`, `modified_user` set to the recipient, `realm` set to the recipient's realm, and `acting_user=None`.
- That row's `extra_data` contains a string field `email_id`: the email template hash, i.e. the first 32 hex characters of the SHA-256 of the raw Markdown template file contents (the same hash `custom_email_sender` already computes).
- That row's `extra_data` contains a string field `email_subject`: the resolved subject line of the sent email.
- On subsequent sends of the same template (same `email_id`), targeted sends (`-u`/`-r`) exclude users who already have a `CUSTOM_EMAIL_SENT` entry for that `email_id`, matched by user.
- Marketing sends (`--marketing` / distinct-email mode) exclude recipients whose delivery email case-insensitively matches the delivery email of any user already logged for that `email_id`, in addition to the existing case-insensitive distinct-email dedup among the current run's recipients.
- When one or more users are excluded as already-recipients, the command prints to stdout exactly once: `Excluded {count} users who already received this email`, and prints nothing else for a non-dry-run send.
- Dry-run mode creates no `CUSTOM_EMAIL_SENT` entries.
- If email delivery fails with `EmailNotDeliveredError` from the existing send path, no audit log entry is created for that recipient, so the user is retried on a future send.

## Notes

- The `email_id` is derived from the template contents, so editing the Markdown template produces a new ID and resets the dedup for that email. That limitation is acceptable; administrators can handle it manually.
- Consider where the audit-log write belongs: the per-recipient send loop in `zerver/lib/send_email.py` already knows the recipient, the template hash, and the resolved subject, and already handles the delivery-failure path, so success/failure can be distinguished per recipient there.
