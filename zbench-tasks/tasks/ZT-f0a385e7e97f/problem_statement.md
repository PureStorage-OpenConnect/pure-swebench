# Rename the Clubhouse integration to Shortcut

## Background

Zulip ships an incoming webhook integration for the project-management tool **Clubhouse**. The vendor has rebranded: the product is now called **Shortcut**, its web app moved from `app.clubhouse.io` to `app.shortcut.com`, and its logo changed. Zulip's integration must be updated to reflect this rebrand while keeping existing customer configurations working.

## Current behavior

- The integration is registered in the incoming-webhook integration registry (`INCOMING_WEBHOOK_INTEGRATIONS` in `zerver/lib/integrations.py`) under the name `clubhouse`, in the `project-management` category, with display name "Clubhouse" and Clubhouse logo assets.
- The webhook implementation lives in `zerver/webhooks/clubhouse/` (view, docs, fixtures), following Zulip's convention that an integration named `<name>` is served at `/api/v1/external/<name>` by `zerver/webhooks/<name>/view.py` exposing a function `api_<name>_webhook`.
- Documentation, screenshots, and any UI references use the Clubhouse name and branding.

## Required behavior

1. **Rename the integration to `shortcut`.** The registry entry's name/slug becomes `shortcut`, still under the `project-management` category, with the display name "Shortcut" and Shortcut logo/branding. The webhook module moves to `zerver/webhooks/shortcut/`, and the handler function is renamed accordingly (see interface requirements). The primary webhook URL becomes `/api/v1/external/shortcut?api_key=...&stream=...`.
2. **Keep old URLs working.** Organizations already have webhooks pointed at `/api/v1/external/clubhouse`. Register `clubhouse` as a legacy alias of the renamed integration so that requests to the old endpoint continue to be accepted and processed identically by the same handler. New documentation and generated URLs should only advertise the `shortcut` name; the alias exists purely for backward compatibility. Use (or introduce, if the codebase lacks one) the framework's mechanism for giving a webhook integration a legacy name so the alias is handled generically rather than by duplicating the integration.
3. **Message content follows the payload, not hardcoded branding.** The bot messages this integration produces must keep their existing structure and formatting. Links and names in messages must come from the webhook payload (e.g., the `app_url` fields, which now contain `https://app.shortcut.com/...` URLs) — nothing in the message-formatting code should hardcode the old `clubhouse.io` domain. Payloads referencing `app.shortcut.com` must produce messages linking to those Shortcut URLs.
4. **Update user-facing materials.** The integration's documentation page, help text, and any listings should describe the integration as Shortcut (it is reasonable to note it was formerly known as Clubhouse). Update sample payload fixtures and screenshots/logo assets to use the Shortcut name and `app.shortcut.com` URLs. Update any other references to the old name across the codebase (e.g., integration listings, docs indexes, bot naming defaults) so the rename is consistent.

## Interface requirements

- The incoming webhook integration previously named `clubhouse` is registered in `INCOMING_WEBHOOK_INTEGRATIONS` under the name `shortcut`, in the `project-management` category.
- The webhook is served at the endpoint `/api/v1/external/shortcut` (endpoint name derived from the integration slug per Zulip's incoming-webhook framework convention).
- Per that convention, the handler lives at `zerver.webhooks.shortcut.view` and is exposed as `api_shortcut_webhook`.
- The old name `clubhouse` is retained as a legacy alias: requests to `/api/v1/external/clubhouse` must continue to work and route to the same handler.
- Bot message structure is unchanged; only branding follows the payload. Messages must render the URLs and names supplied in the payload rather than hardcoding the old `clubhouse.io` domain.

## Acceptance criteria

- POSTing a valid Shortcut payload (e.g., a story-create event whose `app_url` is `https://app.shortcut.com/...`) to `/api/v1/external/shortcut` produces the same bot messages the integration produced before the rename, with links pointing at the payload's `app.shortcut.com` URLs.
- The same payload POSTed to `/api/v1/external/clubhouse` is accepted and produces identical results.
- The integrations catalog lists Shortcut (not Clubhouse) under project management, with working documentation and logo.
