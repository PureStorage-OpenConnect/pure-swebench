# Include the data-deletion date in organization deactivation emails

## Background

Zulip supports deactivating an organization (realm) via `do_deactivate_realm` in `zerver/actions/realm_settings.py`. When deactivation is performed with `email_owners=True`, a notification email is sent to each owner of the organization. The email's wording varies by recipient: the owner who performed the deactivation gets a body beginning "You have deactivated your Zulip organization, <realm name>, on <date>", while other owners get a body beginning "Your Zulip organization, <realm name>, was deactivated by <acting user> on <date>". The subject line is of the form "Your Zulip organization <realm name> has been deactivated".

Separately, deactivation supports scheduling deletion of the organization's data: `do_deactivate_realm` accepts a `deletion_delay_days` argument. A positive value schedules the organization's data to be permanently deleted that many days after deactivation; a value of `0` means the data is scrubbed immediately as part of deactivation (via `do_scrub_realm`); `None` means no data deletion is scheduled.

## Problem

The deactivation notification email currently tells owners that the organization was deactivated, but says nothing about what will happen to the organization's data. Owners have no way to know from the email whether their data has already been deleted, or when it is scheduled to be deleted.

## Required behavior

Add a sentence about data deletion to the deactivation notification email, appearing as the second line of the email body (immediately after the existing sentence stating that the organization was deactivated). The existing first line, subject, and per-recipient wording must be preserved.

1. **Scheduled (future) deletion** — when the organization is deactivated with `deletion_delay_days > 0`, the email sent to each owner must state:

   > All data associated with this organization will be permanently deleted on `<date>`.

   where `<date>` is the scheduled deletion date (deactivation time plus the configured delay), rendered in that recipient owner's timezone. For example, deactivating with `deletion_delay_days=14` must produce an email whose body contains "All data associated with this organization will be permanently deleted on" followed by the date 14 days out.

2. **Immediate deletion** — when the organization is deactivated with `deletion_delay_days=0`, the data is scrubbed immediately (`do_scrub_realm` is invoked once with the realm and `acting_user=None`), and the email sent to each owner must contain the exact sentence:

   > All data associated with this organization has been permanently deleted.

   Note that the notification emails must still be delivered to the owners in this case, even though the organization's data (including user records needed to address the email) is destroyed during the same deactivation call — so recipient information must be captured before the scrub happens, and the email is written in the past tense.

3. **No deletion scheduled** — when deactivation happens without any data deletion (`deletion_delay_days=None`), the email keeps its current content and includes neither sentence.

Both flavors of the email (the one to the acting owner and the one to other owners) must include the applicable data-deletion sentence.

## Interface requirements

- When an organization is deactivated with a scheduled data-deletion delay (`deletion_delay_days > 0` passed to `do_deactivate_realm`), the deactivation email sent to each owner must include the sentence "All data associated with this organization will be permanently deleted on" followed by the scheduled deletion date, rendered in that owner's timezone.
- When an organization is deactivated with immediate data deletion (`deletion_delay_days=0` passed to `do_deactivate_realm`), the deactivation email sent to owners must include the exact sentence "All data associated with this organization has been permanently deleted."
