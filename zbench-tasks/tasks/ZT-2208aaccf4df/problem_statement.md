# Replace template-hash email tracking with an explicit campaign name in `send_custom_email`

## Background

Zulip's `send_custom_email` machinery (the `send_custom_email` management command in `zerver/management/commands/`, backed by the `send_custom_email` and `send_custom_server_email` functions in `zerver/lib/send_email.py`) lets server administrators send a one-off email, rendered from a Markdown template file, to a set of users or to remote Zulip servers.

To support auditing and to avoid emailing the same user twice for the same campaign (e.g. when a long send is interrupted and re-run), each successful send is recorded in `RealmAuditLog` with event type `CUSTOM_EMAIL_SENT`. Currently, the identifier stored for the campaign is derived from the email's content: a SHA-256 hash of the Markdown template text, truncated to its first 32 hex characters, stored in the audit-log row's `extra_data` under the key `email_id` (alongside `email_subject`). On subsequent runs, recipients who already have a `CUSTOM_EMAIL_SENT` audit-log entry with the same `email_id` hash are excluded from the send.

This content-hash scheme is fragile: any edit to the template (even fixing a typo mid-campaign) changes the hash, silently defeating duplicate prevention, and the opaque hash makes audit-log entries hard to interpret.

## Required behavior

Replace the content-hash identifier with an explicit, operator-chosen **campaign name**:

1. **Management command.** The `send_custom_email` management command must accept a **required** `--campaign-name` CLI flag: a unique string identifier for the email campaign (e.g. `q4_2025_update`). Invocations without it should fail with the standard argparse missing-argument error. The flag must work in both normal and `--dry-run` invocations (dry runs still render/print the email and send nothing, as today).

2. **Library functions.** The `options` dict accepted by the existing `send_custom_email` and `send_custom_server_email` functions gains a **required** string key `campaign_name`, carrying the same campaign identifier (mirroring the CLI flag, as all other keys in that dict do — `markdown_template_path`, `subject`, `from_name`, `reply_to`, etc.). The management command passes its flag value through in this key. All existing behavior of these functions (rendering, custom headers, `add_context` hooks, dry-run mode, the `DoubledEmailArgumentError` raised when a subject or from-name is supplied both in template headers and in `options`) must be unchanged apart from the new required key.

3. **Audit logging.** `RealmAuditLog` entries of event type `CUSTOM_EMAIL_SENT` must record the campaign identifier in `extra_data` under the key `campaign_name`, **replacing** the previous `email_id` key that held the truncated SHA-256 of the template text. `extra_data` must continue to include `email_subject`. One entry is still created per recipient actually emailed.

4. **Duplicate prevention.** Exclusion of already-emailed recipients must be keyed on the `campaign_name` value rather than the template hash: when the command is re-run with the same `--campaign-name`, users who already have a `CUSTOM_EMAIL_SENT` audit-log entry whose `extra_data[\"campaign_name\"]` matches are skipped (no email, no new audit-log row for them), while new recipients in the list are emailed and logged normally. Re-running with a *different* campaign name must treat everyone as fresh recipients. The template-hash computation should no longer play any role in tracking or dedup.

### Concrete example

Running the command with `--campaign-name=test_campaign_01` against users A and B sends two emails and creates two `CUSTOM_EMAIL_SENT` audit rows, each with `extra_data` containing `campaign_name: \"test_campaign_01\"` and the email's subject. Re-running with the same campaign name against users A, B, and C sends exactly one email (to C) and adds exactly one new audit row, bringing the total to three.

## Interface requirements

- The `send_custom_email` management command gains a required CLI flag `--campaign-name`: a unique string identifier for the email campaign (e.g. 'q4_2025_update'), used instead of the template-content hash to track and prevent duplicate sends.
- The `options` dict accepted by the existing `send_custom_email` and `send_custom_server_email` functions gains a required string key `campaign_name`, carrying the same campaign identifier (mirroring the CLI flag, as all other keys in that dict do).
- RealmAuditLog entries of event type CUSTOM_EMAIL_SENT record the campaign identifier in `extra_data` under the key `campaign_name` (replacing the previous `email_id` key that held a truncated SHA-256 of the template text); `extra_data` continues to include `email_subject`. Duplicate-send exclusion of recipients is keyed on this `campaign_name` value rather than the template hash.
