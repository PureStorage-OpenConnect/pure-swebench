# ZT-c5200e8b05b2 -- deliver_scheduled_emails: Use a queue, instead of infinite retries.

- lang: py   issue: #32463   tier: B
- fix: https://github.com/zulip/zulip/commit/c5200e8b05b23b14f3b8b8e2b6a98cb74e18c709
- f2p: zerver.tests.test_email_notifications.TestFollowupEmails.test_followup_emails_for_demo_realms, zerver.tests.test_email_notifications.TestFollowupEmails.test_followup_emails_for_regular_realms, zerver.tests.test_invite.InviteUserTest.test_invitation_reminder_email, zerver.tests.test_queue_worker.WorkerTest.test_email_sending_worker_retries, zerver.tests.test_users.ActivateTest.test_deliver_scheduled_emails, zerver.tests.test_users.ActivateTest.test_deliver_scheduled_emails_no_addressees
- p2p: zerver.tests.test_send_email

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real high-priority bug (scheduled emails retrying every 10s on certain exceptions) fixed by routing delivery through a new 'deferred_email_senders' queue with proper retry semantics. The hidden tests grade observable, deterministic outcomes: emails land in django's outbox (assert_length on outbox counts), on-commit queue callbacks fire, and the worker retries via the queue on EmailNotDeliveredError. No exact-string snapshots, no API_FEATURE_LEVEL/migration/version-gated assertions. Tests do import the renamed entry points (queue_scheduled_emails, ImmediateEmailSenderWorker), but that is a naming/spec-gap concern for later stages, not a verifiability failure \u2014 the tests fail before the fix and pass after based on behavior."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The library function `zerver.lib.send_email.deliver_scheduled_emails` is renamed to `queue_scheduled_emails` to reflect its new behavior: instead of building and sending the email synchronously, it enqueues the email-sending event for asynchronous delivery, and it must do so via a Django on-commit hook so the event is published only after the current database transaction commits. It still deletes the processed ScheduledEmail row, and the end-to-end result (once the queued event is consumed) is identical to the previous direct send, including the existing behavior of logging to the `zulip.send_email` logger and sending nothing when the scheduled email has no remaining recipients.",
    "The email-sending queue worker class exported from `zerver.worker.email_senders` (previously `EmailSendingWorker`) is renamed to `ImmediateEmailSenderWorker`; it remains importable from that module, remains the registered worker for the `email_senders` queue, and retains the existing behavior of retrying events when email delivery fails with `EmailNotDeliveredError`."
  ],
  "reason": "The test checks pre-existing user-visible outcomes (emails in Django's outbox, ScheduledEmail deletion, envelope/display from-addresses, the existing `zulip.send_email` log) but binds to two new names introduced by the fix: the renamed library function `queue_scheduled_emails` and the renamed worker class `ImmediateEmailSenderWorker`, plus the on-commit semantics (the tests wrap calls in `captureOnCommitCallbacks(execute=True)`, which only passes if enqueueing happens via transaction.on_commit). Both names are renames of existing surface a refactor ticket would legitimately dictate \u2014 the function is the module-level API consumed by the `deliver_scheduled_emails` management command, and the worker class was already imported directly by the pre-existing test at the base commit, so its name/location is established contract surface rather than a private helper. The test does not reach into internals the fix invents: it never references the new `deferred_email_senders` queue name, the `email_senders_base` module, or the `DeferredEmailSenderWorker`/module-split layout, so any implementation honoring the two named renames and the on-commit queueing semantics passes. Given those items in the brief, the test grades correctness, not name-guessing."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_email_notifications.TestFollowupEmails.test_followup_emails_for_regular_realms",
    "zerver.tests.test_email_notifications.TestFollowupEmails.test_followup_emails_for_demo_realms",
    "zerver.tests.test_invite.InviteUserTest.test_invitation_reminder_email",
    "zerver.tests.test_queue_worker.WorkerTest.test_email_sending_worker_retries",
    "zerver.tests.test_users.ActivateTest.test_deliver_scheduled_emails",
    "zerver.tests.test_users.ActivateTest.test_deliver_scheduled_emails_no_addressees"
  ],
  "reason": "The diff modifies existing test bodies (no new tests): it renames deliver_scheduled_emails to queue_scheduled_emails wrapped in captureOnCommitCallbacks, and swaps EmailSendingWorker for ImmediateEmailSenderWorker. Enclosing class/method names were verified by fetching each file at the corresponding upstream Zulip commit c5200e8b and locating the changed line numbers."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the failure mode concretely (synchronous send in deliver_scheduled_emails, 10-second retry loop in the management command) and leaves the design open, but the interface requirements and behavior evidence pin down the chosen design: rename deliver_scheduled_emails to queue_scheduled_emails, enqueue via transaction.on_commit instead of sending directly, delete the row, preserve empty-recipient warning/delete semantics, and rename EmailSendingWorker to ImmediateEmailSenderWorker while keeping its queue registration and retry behavior. That is a determinate, checkable outcome two engineers would implement compatibly."
}
