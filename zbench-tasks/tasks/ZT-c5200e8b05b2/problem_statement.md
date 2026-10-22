# Stop the scheduled-email deliverer from retrying failed sends every 10 seconds by routing delivery through the email-sending queue

## Background

Zulip has two distinct email-delivery paths:

1. The `email_senders` queue worker (`zerver/worker/email_senders.py`), which consumes events from the `email_senders` queue and sends them. This worker sits on top of the generic queue-worker infrastructure, which already has a retry/backoff mechanism: when a send fails with `zerver.lib.send_email.EmailNotDeliveredError`, the event is retried with the standard `failed_tries` bookkeeping rather than being retried in a tight loop.

2. The scheduled-email system: rows in the `ScheduledEmail` model are picked up by the `deliver_scheduled_emails` management command (`zerver/management/commands/deliver_scheduled_emails.py`), which loops forever, selects the next due `ScheduledEmail` row (with `select_for_update(skip_locked=True)`), and calls `zerver.lib.send_email.deliver_scheduled_emails(job)`. That library function loads the stored email data, fills in the recipients (`to_user_ids` from the row's `users` relation and/or `to_emails` from the row's `address`), calls `handle_send_email_format_changes(data)`, then **synchronously** builds and sends the email via `send_email(**data)`, and finally deletes the `ScheduledEmail` row.

## Problem

Because the scheduled-email path sends synchronously and only deletes the row on success, a send that raises `EmailNotDeliveredError` leaves the `ScheduledEmail` row in place. The management command catches the exception, logs a warning, and loops again — so it re-selects the same row and retries the same undeliverable email indefinitely, as often as every 10 seconds. There is no failure counter or backoff on this path, unlike the queue-worker path.

## Required behavior

Unify the two paths: the scheduled-email machinery should no longer send email itself. Instead, when a `ScheduledEmail` comes due, it should enqueue an email-sending event onto the `email_senders` queue and delete the row; actual delivery (and any retry-on-failure handling) is then owned entirely by the existing queue worker and its `failed_tries` retry mechanism.

Concretely:

- The library function currently named `zerver.lib.send_email.deliver_scheduled_emails` must be renamed to `queue_scheduled_emails`, and its behavior must change from "build and send the email synchronously" to "publish an email-sending event to the `email_senders` queue for asynchronous delivery."
- The queue event must be published via a Django on-commit hook (`transaction.on_commit`), so the event only reaches the queue after the surrounding database transaction commits. This matters because the management command processes each job inside a transaction holding a row lock; enqueueing before commit could let the worker race the deletion of the `ScheduledEmail` row.
- `queue_scheduled_emails` must still delete the processed `ScheduledEmail` row as part of processing it.
- The end-to-end observable result, once the queued event is consumed by the worker, must be identical to what the old synchronous send produced: the same recipients (user IDs from the row's `users` relation, and/or the row's `address`), the same email content, and the same logging to the `zulip.send_email` logger.
- The existing degenerate-row handling must be preserved: if a `ScheduledEmail` has neither associated users nor an `address` (e.g. all recipient users were deactivated after scheduling), the function logs a warning via the `zulip.send_email` logger, deletes the row, and sends nothing — no queue event is published in that case.
- The management command should be updated to call the renamed function; since sending is no longer synchronous there, it no longer needs to handle `EmailNotDeliveredError` around that call.
- All existing callers/importers of the old `deliver_scheduled_emails` library function must be updated to the new name.

## Worker rename

To make the naming reflect the two delivery modes, the email-sending queue worker class in `zerver.worker.email_senders` (currently `EmailSendingWorker`) must be renamed to `ImmediateEmailSenderWorker`. It must:

- remain importable from `zerver.worker.email_senders`,
- remain the registered worker for the `email_senders` queue, and
- retain its existing behavior of retrying events (via the standard queue-worker retry mechanism) when delivery fails with `EmailNotDeliveredError`.

Update any references to the old class name elsewhere in the codebase.

## Interface requirements

- `zerver.lib.send_email.queue_scheduled_emails` — the renamed scheduled-email processing function. It enqueues the email-sending event for asynchronous delivery via a Django on-commit hook (the event is published only after the current transaction commits), deletes the processed `ScheduledEmail` row, and preserves the previous end-to-end behavior once the event is consumed, including logging to the `zulip.send_email` logger and sending nothing when the scheduled email has no remaining recipients.
- `zerver.worker.email_senders.ImmediateEmailSenderWorker` — the renamed email-sending queue worker class. It remains importable from that module, remains the registered worker for the `email_senders` queue, and retains the existing retry-on-`EmailNotDeliveredError` behavior.
