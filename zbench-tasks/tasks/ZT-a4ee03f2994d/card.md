# ZT-a4ee03f2994d -- discord_auth: Support authenticating special Discord email.

- lang: py   issue: #38149   tier: B
- fix: https://github.com/zulip/zulip/commit/a4ee03f2994dc7c5ae718deda0b7ed2353bc8946
- f2p: zerver.tests.test_auth_backends.DiscordAuthBackendTest.test_authenticate_special_emails_with_encoded_user_id
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real engineering workflow: extend Discord OAuth to authenticate imported users whose emails were encoded from Discord user IDs by the import tool. The hidden test grades observable behavior deterministically \u2014 it creates a user with the encoded email, runs the social-auth flow with a mismatched Discord email, and asserts the login resolves to the correct account (delivery_email, full_name, subdomain, 302 redirect). No snapshot pinning or format brittleness; assertions target specific outcome fields. The test does import the EMAIL_WITH_ENCODED_DISCORD_ID constant by name, but that is a naming/spec gap handled by later stages, and the email-encoding scheme itself is the observable contract with the import tool."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The module `zproject.backends` exposes a public constant `EMAIL_WITH_ENCODED_DISCORD_ID`: a Python format string with a single named placeholder `discord_user_id` (e.g. \"{discord_user_id}@discordexport.zulip.com\") that defines the placeholder email address the Discord data-import tool assigns to imported users whose real email is unavailable; other components (the import tool, the auth backend, and any caller needing to construct such an address) must build these addresses via this constant.",
    "During Discord OAuth authentication, if no active user in the realm matches the email returned by Discord, the backend must fall back to looking up a user whose Zulip delivery email equals EMAIL_WITH_ENCODED_DISCORD_ID formatted with the authenticating user's Discord user ID (the `id` field of Discord's OAuth user response), and authenticate that user if found.",
    "A successful fallback login behaves as a normal successful social login: it redirects (HTTP 302) to the subdomain login endpoint, and the login payload carries the matched user's existing Zulip delivery email (not the email Discord reported), the full name from Discord's `global_name`, and the realm subdomain."
  ],
  "reason": "The test asserts user-visible login behavior (successful auth, redirect, session payload contents) through the pre-existing social-auth test flow, and Discord's `id`/`global_name` response fields are Discord's own external API, not invented names. The only new bindings are the constant `EMAIL_WITH_ENCODED_DISCORD_ID` in `zproject.backends` \u2014 including its exact name, module location, and `discord_user_id` placeholder key, all pinned by the test's import and `.format()` call \u2014 plus the fallback-lookup behavior itself. A cross-component shared constant defining the import tool's encoded-email scheme is exactly the kind of surface a ticket would dictate (the import tool and auth backend must agree on it), so with these items in the brief the test grades correctness rather than name-guessing. Notably, the constant's concrete domain value is not asserted (the test round-trips through the constant itself), so only the name/placeholder contract is required."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product goal (let Discord OAuth users claim imported accounts via a special encoded-ID address format), the behavior evidence pins down the observable outcome (fallback match on Discord `id`, login payload fields, 302 to the subdomain login endpoint, no email-choice screen), and the interface requirements fix the exact constant name, module, placeholder name, and semantics. Together these give a determinate, checkable outcome two engineers would implement compatibly."
}
