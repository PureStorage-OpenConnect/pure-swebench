# ZT-194dfbc84d25 -- integrations: Add common framework for webhook signature verification.

- lang: py   issue: #19774   tier: B
- fix: https://github.com/zulip/zulip/commit/194dfbc84d25b0bf4247876aa15fa04a130271e6
- f2p: zerver.tests.test_webhooks_common.WebhooksCommonTestCase.test_validate_webhook_signature
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature (backend framework)",
  "reason": "Adds a common webhook HMAC signature verification helper \u2014 a real, assignable engineering task with observable behavior. The hidden test grades deterministically on outcome: a correctly computed HMAC-SHA256 signature passes, an invalid signature raises JsonableError, and a missing webhook_secret raises JsonableError. HMAC computation is fully deterministic, and the assertRaisesRegex checks match short user-facing error messages rather than pinning long output strings or snapshots. The test fails before the change (function doesn't exist) and passes after, so fail-before/pass-after verifiability holds. Not in any drop category."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "A new function `validate_webhook_signature(request, payload, signature)` in `zerver.lib.webhooks.common`, intended as the shared helper webhook integrations call to verify incoming payload signatures; it takes the Django HttpRequest, the raw payload as a string, and the signature string provided by the sender, returning None on success and raising `JsonableError` on failure.",
    "Signature verification computes an HMAC of the payload using SHA-256 by default, keyed by the shared secret, and compares its lowercase hex digest against the provided signature string.",
    "The shared secret is supplied by the sender as a URL query parameter named `webhook_secret` on the webhook URL.",
    "When the computed digest does not match the provided signature, the function raises `JsonableError` with the user-facing message \"Webhook signature verification failed.\"",
    "When the `webhook_secret` query parameter is absent, the function raises `JsonableError` with the user-facing message \"The webhook secret is missing. Please set the webhook_secret while generating the URL.\"",
    "A new server setting `VERIFY_WEBHOOK_SIGNATURES` (boolean, default True in production defaults) gates the feature: when False, `validate_webhook_signature` is a no-op that returns without checking anything.",
    "The Zulip test-suite settings must default `VERIFY_WEBHOOK_SIGNATURES` to False so existing webhook behavior is unchanged unless a caller explicitly enables verification."
  ],
  "reason": "The test does not touch pre-existing interfaces, so it is not clean, but everything it binds to is legitimate contract surface a ticket would dictate: the name and call shape of a new public library helper (`validate_webhook_signature` lives in the shared `zerver.lib.webhooks.common` module, which the test already imports other public helpers from), a documented settings flag (`VERIFY_WEBHOOK_SIGNATURES`), a user-visible URL query parameter (`webhook_secret`), the HMAC-SHA256 hex-digest verification semantics, and two exact user-facing error strings asserted via regex. No private helpers, internal mock targets, or internal data-structure layout are referenced \u2014 given the contract above, the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue is thin (just a request to verify Stripe webhook signatures), but combined with the evidence and interface requirements, the observable behavior is fully determinate: the helper's module and name, its argument order and types, the HMAC-SHA256 lowercase-hex scheme, the webhook_secret query-parameter source, both exact error messages, the gating setting name with its production default of True and test/dev default of False, and the no-op behavior when disabled. Two engineers working from this brief would produce compatible implementations."
}
