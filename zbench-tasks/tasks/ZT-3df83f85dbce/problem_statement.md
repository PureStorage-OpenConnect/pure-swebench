# Rename the HelloSign integration to Dropbox Sign

## Background

Zulip ships an incoming webhook integration for the e-signature service HelloSign, implemented under `zerver/webhooks/hellosign/` and reachable at the endpoint `/api/v1/external/hellosign`. The vendor has rebranded: HelloSign is now **Dropbox Sign** (websites `dropboxsign.com` / `api.dropboxsign.com` instead of `hellosign.com` / `api.hellosign.com`). Zulip's integration still uses the old name everywhere — the webhook slug and URL, the Python package, the integration registration, the display name shown in the integrations catalog, the documentation page, the logo, and the screenshot.

## Required behavior

Rename the integration to Dropbox Sign throughout the product, while keeping existing customer webhook URLs working:

1. **New slug and endpoint.** The integration's slug becomes `dropboxsign`, so its webhook endpoint is `/api/v1/external/dropboxsign`. Following the webhook framework's convention that an integration's code lives in a directory matching its slug, the integration's module (view, tests, fixtures, docs) moves from `zerver/webhooks/hellosign/` to `zerver/webhooks/dropboxsign/`.

2. **Display name.** The integration's user-visible name (integrations catalog, documentation, generated messages/metadata that reference the integration name) becomes "Dropbox Sign". Update the integration's logo and documentation screenshot to Dropbox Sign branding, and update the integration documentation text to refer to Dropbox Sign.

3. **Backwards compatibility for existing webhook URLs.** Any customer who configured a webhook against the old endpoint must not be broken. Requests to `/api/v1/external/hellosign` (with the same query parameters, e.g. `api_key` and `stream`) must continue to be accepted and handled by the renamed integration, producing exactly the same result as the equivalent request to `/api/v1/external/dropboxsign`. Zulip's integration framework already has a `legacy_names` mechanism for registering old slugs of a renamed integration; register `hellosign` as a legacy name of `dropboxsign` using that mechanism.

4. **Message formatting is unchanged.** This is a pure rename: given the same Dropbox Sign / HelloSign signature-request payload (the vendor's JSON payload posted as the `json` form field), the integration must produce the same Zulip topic and the same notification message text as before. For example, a signature request titled "NDA with Acme Co." where Jill has signed and Jack's signature is still awaited must produce the topic `NDA with Acme Co.` and the message:

   > The `NDA with Acme Co.` document is awaiting the signature of Jack, and was just signed by Jill.

   All existing behaviors — topic taken from the signature request's title, custom subject handling, wording for one signatory, multiple signatories in various states, etc. — must be preserved byte-for-byte.

5. **Internal naming and sample data.** Internal identifiers should follow the new name (e.g. the webhook's test class and any name-derived identifiers use "DropboxSign" rather than "HelloSign"). The integration's sample/fixture payloads should be updated to reflect the vendor's new domains — e.g. `https://www.dropboxsign.com/...`, `https://api.dropboxsign.com/...`, `https://app.dropboxsign.com/...`, and example addresses like `me@dropboxsign.com` in place of the corresponding `hellosign.com` values — without altering the fields the message formatter relies on (titles, signer names, signer statuses), so generated messages are unchanged.

6. **Housekeeping.** Update any other references to the integration's slug or name elsewhere in the codebase (e.g. integration lists, documentation indexes, fixture/screenshot generation configs) so nothing still points at a `hellosign` integration directory that no longer exists, while the legacy URL keeps working.

## Interface requirements

- The HelloSign incoming webhook integration is renamed to the slug `dropboxsign` (display name "Dropbox Sign"): its webhook endpoint becomes `/api/v1/external/dropboxsign`, and per Zulip's existing webhook framework convention its module and fixtures live under `zerver/webhooks/dropboxsign/`.
- Webhook URLs using the old slug `hellosign` (`/api/v1/external/hellosign`) must continue to be accepted and routed to the renamed integration, by registering `hellosign` in the integration's `legacy_names` (a registration mechanism that already exists in the codebase).
- The integration's message-formatting behavior is unchanged by the rename: the same signature-request payloads produce the same topic (the signature request's title) and the same notification message text as before.
