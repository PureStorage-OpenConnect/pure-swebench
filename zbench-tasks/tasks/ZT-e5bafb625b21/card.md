# ZT-e5bafb625b21 -- email: Update realm deactivation email for data deletion information.

- lang: py   issue: #24686   tier: B
- fix: https://github.com/zulip/zulip/commit/e5bafb625b21f4d1aa2ce6e10d7a70bab5cea41a
- f2p: zerver.tests.test_realm.RealmTest.test_do_send_realm_deactivation_email_with_immediate_data_deletion
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real engineering task: extend the realm deactivation email to include data-deletion timing, driven by a concrete issue. The change is behavior-observable (email body content varies with deletion_delay_days) and the hidden test grades it deterministically via targeted assertIn substring checks on the email subject/body plus a mock assertion that immediate deletion scrubs the realm \u2014 not exact full-string or snapshot pins, so it fails before and passes after without brittleness."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When an organization is deactivated with a scheduled data-deletion delay (deletion_delay_days > 0 passed to do_deactivate_realm), the deactivation email sent to each owner must include the sentence \"All data associated with this organization will be permanently deleted on\" followed by the scheduled deletion date, rendered in that owner's timezone.",
    "When an organization is deactivated with immediate data deletion (deletion_delay_days=0 passed to do_deactivate_realm), the deactivation email sent to owners must include the exact sentence \"All data associated with this organization has been permanently deleted.\""
  ],
  "reason": "All API surface the test calls (do_deactivate_realm's deletion_delay_days/email_owners parameters, do_scrub_realm and its immediate-deletion invocation, realm.scheduled_deletion_date) pre-exists at the base commit \u2014 the code diff references these without introducing them. The only new bindings are two user-facing email body sentences, which a ticket would legitimately dictate verbatim. The test never touches the fix's internal choices (template context keys like data_already_deleted, or the new parameter added to do_send_realm_deactivation_email, which it exercises only through the public do_deactivate_realm entry point), so with the wording in the brief the test grades correctness, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue specifies the exact two sentences and their position in the email, and the expected-behavior evidence pins down the observable outcomes: the deletion_delay_days parameter on do_deactivate_realm, the exact email subject/body phrasing for both the acting owner and other owners, the future-dated sentence for a positive delay, the past-tense sentence plus immediate do_scrub_realm(realm, acting_user=None) call for a zero delay, and that emails are still delivered despite immediate scrubbing. Together these give a determinate, checkable specification two engineers would implement compatibly."
}
