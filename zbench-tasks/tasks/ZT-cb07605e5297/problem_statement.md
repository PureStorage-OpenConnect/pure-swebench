# Return a user-facing 400 error when an incoming webhook request is missing a required HTTP event header

## Context

Zulip's incoming webhook framework supports integrations whose payloads are dispatched based on an HTTP header (for example, the Groove integration dispatches on the `X-Groove-Event` header). The shared webhook helper code in `zerver/lib/webhooks/common.py` validates that such a header is present when extracting it from the request; when the header is absent it raises `MissingHTTPEventHeaderError`. As part of this handling, the framework also notifies the bot owner (via a private message from the notification bot) that the integration received a request missing the expected header, so the owner can debug their integration setup.

## Current behavior

When a webhook request arrives without the required event header, `MissingHTTPEventHeaderError` is treated like an unexpected/anomalous webhook failure:

- The request fails with an HTTP 500 response.
- The failure is logged through the anomalous-webhook-payload logging path (the `zulip.zerver.webhooks.anomalous` logger), which means it is also reported to Sentry as a server error.

This is wrong: a missing header is a *client* error (a misconfigured sender), not a server bug. It should not page operators or pollute Sentry.

## Required behavior

When a webhook view raises `MissingHTTPEventHeaderError` because a required HTTP event header is absent:

1. The API must respond with a normal Zulip JSON client error — HTTP status 400 with a standard error body (`"result": "error"`) whose `msg` is the exception's message, e.g. for the Groove integration:

   ```
   Missing the HTTP event header 'X-Groove-Event'
   ```

2. Nothing must be logged to the anomalous webhook logger (`zulip.zerver.webhooks.anomalous`) for this condition — no INFO-or-higher records at all — and the error must not be reported to Sentry as a 500.

3. The existing bot-owner notification must be preserved: the bot owner still receives the private message explaining that the integration received a request missing the expected HTTP header, exactly as before. Only the HTTP response status/shape and the server-side logging/error-reporting change.

## Notes for implementation

- `MissingHTTPEventHeaderError` is raised from the shared header-extraction helper used by multiple integrations; the fix should apply generically to any integration that requires an event header, not just Groove.
- The natural approach is to make `MissingHTTPEventHeaderError` behave as (or be handled like) a standard `JsonableError`-style client error with HTTP 400 semantics, rather than being caught by the anomalous-payload/unexpected-event handling that produces 500s and log records.
- A concrete way to verify: POST a valid Groove payload body (form-encoded) to a Groove webhook bot URL without the `X-Groove-Event` header. The response must be a 400 JSON error with the message quoted above, no record must appear on the `zulip.zerver.webhooks.anomalous` logger, and the bot owner must still receive the debugging notification message.
