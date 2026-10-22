# ZT-31c533354369 -- webhooks/sentry: Add support for error events.

- lang: py   issue: #24146   tier: B
- fix: https://github.com/zulip/zulip/commit/31c533354369695966f028d2cab7df09eefdc9a2
- f2p: zerver.webhooks.sentry.tests.SentryHookTests.test_error_for_exception_javascript, zerver.webhooks.sentry.tests.SentryHookTests.test_issue_assigned_to_individual
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature (incoming webhook event support)",
  "reason": "Real, assignable engineering task: extend the Sentry webhook to handle the 'error' event type, backed by an upstream issue. The hidden test fails before (payloads with an 'error' key are unsupported) and passes after, grading observable outcome deterministically via a fixed fixture. Although the test asserts the full message string, that is the standard Zulip webhook test pattern where the rendered Zulip message IS the behavior under test \u2014 it's deterministic, derived entirely from the fixture, and not an incidental snapshot of unrelated formatting."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test exercises only the pre-existing public Sentry webhook endpoint via the standard check_webhook flow: it POSTs a fixture payload (which the test diff itself supplies) and asserts the user-visible topic and message. The expected message format (':orange_circle: **New exception:** ...' with level/timestamp/filename quote block and traceback) is exactly the format the base-commit handler `handle_exception_or_log_entry_payloads` already produces for `event`-keyed payloads \u2014 the fix merely routes the new `error`-keyed payload shape (a Sentry-defined key, not an author invention) through existing formatting. The test binds to no new function names, settings, fields, or internal structures; any solver who makes 'error' payloads behave like the existing 'event' payloads passes. The topic and message content derive from the payload data through pre-existing user-visible behavior, so the test grades correctness, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue identifies the exact failure (payloads with data['error'] rejected as unsupported by the Sentry webhook) and the expected-behavior evidence pins down the precise observable output \u2014 topic name and full message rendering \u2014 for a representative error payload, so a determinate, checkable requirement can be stated."
}
