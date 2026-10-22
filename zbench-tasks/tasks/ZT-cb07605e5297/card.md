# ZT-cb07605e5297 -- integrations: Prevent logging of MissingHTTPEventHeaderError.

- lang: py   issue: #34623   tier: B
- fix: https://github.com/zulip/zulip/commit/cb07605e52973e13e4283a19922b42ccefef3c51
- f2p: zerver.tests.test_webhooks_common.MissingEventHeaderTestCase.test_missing_event_header
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real behavior change: MissingHTTPEventHeaderError no longer spams the webhook logger while the client still gets a 400. The hidden test grades observable outcomes deterministically (assertNoLogs on the webhook logger plus the JSON error response) \u2014 it fails before the fix and passes after, with no snapshot or exact-format brittleness."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test binds only to surfaces that exist at the base commit: the webhook endpoint URL, the logger name 'zulip.zerver.webhooks.anomalous' (already referenced by the original test), and the pre-existing user-facing error message \"Missing the HTTP event header 'X-Groove-Event'\". The change flips assertLogs to assertNoLogs, asserting a user/operator-visible outcome \u2014 that a malformed-request client error no longer produces an entry on the existing anomalous-webhook logger while still returning the same JSON error. Nothing in the test references the fix's internal choices (the MissingHTTPEventHeaderError class, log_exception_to_webhook_logger, or the isinstance check), so any implementation that suppresses this logging passes. No new names must be guessed."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_webhooks_common.MissingEventHeaderTestCase.test_missing_event_header"
  ],
  "reason": "The diff modifies a single existing test method, test_missing_event_header, in the MissingEventHeaderTestCase class within zerver/tests/test_webhooks_common.py, changing an assertLogs check to assertNoLogs and removing the log-output assertion."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the intent (convert the 500/Sentry-reported MissingHTTPEventHeaderError into a client-facing error that notifies the bot owner), and the expected-behavior evidence pins down the observable outcome: a JSON 400 error with the exception message 'Missing the HTTP event header 'X-Groove-Event'', no records on the zulip.zerver.webhooks.anomalous logger, and the bot-owner notification flow preserved. This is determinate and checkable."
}
