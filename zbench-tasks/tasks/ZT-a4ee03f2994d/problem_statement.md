# Discord OAuth: authenticate imported users via encoded-Discord-ID placeholder emails

## Background

Zulip supports logging in via Discord OAuth (`zproject.backends`, alongside the GitHub/Google/etc. social auth backends). Separately, Zulip has a Discord data-import tool that creates Zulip accounts from a Discord export. Discord exports do not always include users' email addresses, so the import tool has to assign a placeholder email to such accounts. Today there is no way for the owner of such an imported account to log in via Discord OAuth: the Discord OAuth flow matches accounts only by the email address Discord reports, which will never equal the placeholder address, so these users cannot claim their imported accounts.

## Required behavior

### 1. A canonical placeholder-email format

Define a single canonical format for the placeholder email addresses assigned to imported Discord users whose real email is unavailable. The address encodes the user's unique Discord user ID and uses the domain `discordexport.zulip.com`, i.e. an imported user with Discord ID `123456` gets the address `123456@discordexport.zulip.com` (subject to the exact format defined by the constant described under Interface requirements). Every component that needs to construct such an address — the Discord import tool, the Discord auth backend, and any other caller — must build it from this one shared definition rather than hard-coding the pattern.

### 2. Fallback account matching during Discord OAuth login

Discord's OAuth user-info response includes the user's unique Discord ID in an `id` field, along with `email`, `global_name` (display name), `username`, and `verified`. The Discord auth backend must use this `id` as follows:

- Normal case (unchanged): if an active user in the realm has a delivery email matching the email Discord reports, that user is authenticated as today.
- New fallback: if **no** active user in the realm matches the Discord-reported email, the backend must additionally look for an active user in the realm whose Zulip **delivery email** equals the placeholder address built from the authenticating user's Discord ID (per the format above). If such a user exists, authenticate them as that user.

Example: a user was imported with delivery email `123456@discordexport.zulip.com` (Discord ID `123456`, real email unknown at import time). Later they log in via Discord OAuth; Discord reports `id: "123456"` and `email: "someone@example.com"`, and no Zulip account in the realm has `someone@example.com`. The backend must recognize the ID match and log them into the imported account.

### 3. Fallback login completes like a normal social login

A successful fallback login must behave exactly like any other successful social login, with no extra interstitial (in particular, no email-selection screen):

- The flow ends with an HTTP 302 redirect to the realm's subdomain login endpoint (a URL of the form `http://<realm-host>/accounts/login/subdomain/...`).
- The signed login payload carried into that endpoint must contain:
  - `email`: the matched Zulip user's **existing delivery email** (the placeholder address) — NOT the email Discord reported;
  - `full_name`: the name from Discord's `global_name` field;
  - `subdomain`: the realm's subdomain.
- Any `next` parameter supplied at the start of the flow (e.g. `/user_uploads/image`) must be preserved through the redirect as usual.

If neither the reported email nor the encoded-ID placeholder matches any active user, the existing behavior for an unrecognized social login (e.g. offering registration, per server/realm settings) applies unchanged.

## Interface requirements

- The module `zproject.backends` must expose a public constant `EMAIL_WITH_ENCODED_DISCORD_ID`: a Python format string with a single named placeholder `discord_user_id` (e.g. `"{discord_user_id}@discordexport.zulip.com"`). It defines the placeholder email address the Discord data-import tool assigns to imported users whose real email is unavailable. Other components (the import tool, the auth backend, and any caller needing to construct such an address) must build these addresses via `EMAIL_WITH_ENCODED_DISCORD_ID.format(discord_user_id=...)`.
- During Discord OAuth authentication, if no active user in the realm matches the email returned by Discord, the backend must fall back to looking up a user whose Zulip delivery email equals `EMAIL_WITH_ENCODED_DISCORD_ID` formatted with the authenticating user's Discord user ID (the `id` field of Discord's OAuth user response), and authenticate that user if found.
- A successful fallback login behaves as a normal successful social login: it redirects (HTTP 302) to the subdomain login endpoint, and the login payload carries the matched user's existing Zulip delivery email (not the email Discord reported), the full name from Discord's `global_name`, and the realm subdomain.
