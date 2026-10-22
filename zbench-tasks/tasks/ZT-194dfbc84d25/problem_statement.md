# Add shared webhook signature verification support (motivated by Stripe)

## Background

Some third-party services that send webhooks (Stripe among them) now sign their outgoing webhook payloads so the receiver can verify that a payload genuinely came from the sender and was not tampered with. Zulip's incoming-webhook framework currently has no shared mechanism for verifying such signatures: any request that reaches a webhook endpoint with a valid Zulip bot API key is processed, with no way to check a sender-provided payload signature.

We want to add a reusable, integration-agnostic helper to Zulip's common webhook library that individual integrations (starting with Stripe) can call to verify incoming payload signatures, along with a server-level setting to turn the feature on or off.

## Required behavior

### Verification scheme

Verification is HMAC-based:

1. A shared secret is established between the third-party service and Zulip. On the Zulip side, the secret is supplied as a query parameter named `webhook_secret` on the webhook URL that the administrator configures in the third-party service (i.e., it arrives on each request as part of the request's query string).
2. The expected signature is computed as the HMAC of the raw request payload, keyed by that shared secret, using SHA-256 as the default hash algorithm. Both the secret and the payload are treated as their UTF-8 byte encodings for the HMAC computation.
3. The computed HMAC's lowercase hexadecimal digest is compared against the signature string supplied by the sender (e.g., extracted from a request header by the integration). If they match, verification succeeds.

### Error handling

- If the computed digest does not match the supplied signature, the helper must reject the request by raising Zulip's standard `JsonableError` with the exact user-facing message: `Webhook signature verification failed.`
- If the `webhook_secret` query parameter is not present on the request, the helper must raise `JsonableError` with the exact user-facing message: `The webhook secret is missing. Please set the webhook_secret while generating the URL.`
- On success, the helper simply returns (returns `None`); it does not produce any output.

### Feature gate

- Introduce a new boolean server setting named `VERIFY_WEBHOOK_SIGNATURES` that gates the whole feature.
- In the production/default server settings, it defaults to `True`.
- When the setting is `False`, the verification helper must be a complete no-op: it returns immediately without inspecting the request, payload, or signature, and never raises. This means servers with the setting disabled keep today's behavior exactly.
- In the settings used by Zulip's development/test configuration, `VERIFY_WEBHOOK_SIGNATURES` must default to `False`, so that existing webhook processing is unchanged unless verification is explicitly enabled.

## Interface requirements

- A new function `validate_webhook_signature(request, payload, signature)` in `zerver.lib.webhooks.common`, intended as the shared helper that webhook integrations call to verify incoming payload signatures. It takes the Django `HttpRequest`, the raw payload as a string, and the signature string provided by the sender; it returns `None` on success and raises `JsonableError` on failure.
- Signature verification computes an HMAC of the payload using SHA-256 by default, keyed by the shared secret, and compares its lowercase hex digest against the provided signature string.
- The shared secret is read from the URL query parameter named `webhook_secret` on the incoming request.
- On digest mismatch, the function raises `JsonableError` with the message `Webhook signature verification failed.`
- When the `webhook_secret` query parameter is absent, the function raises `JsonableError` with the message `The webhook secret is missing. Please set the webhook_secret while generating the URL.`
- A new server setting `VERIFY_WEBHOOK_SIGNATURES` (boolean, default `True` in production defaults) gates the feature: when `False`, `validate_webhook_signature` returns without checking anything.
- Zulip's test-suite/development settings must default `VERIFY_WEBHOOK_SIGNATURES` to `False` so existing webhook behavior is unchanged unless verification is explicitly enabled.

## Notes for implementation

- The helper lives in the shared webhook library (`zerver/lib/webhooks/common.py`) precisely so any integration can adopt it; do not hard-code anything Stripe-specific into it (extraction of the signature value from a header is the calling integration's responsibility — the helper receives the signature as a plain string argument).
- Use a constant-time comparison for the digest check, as is standard for HMAC verification.
- User-facing error messages should be marked for translation, consistent with other `JsonableError` messages in the codebase.
