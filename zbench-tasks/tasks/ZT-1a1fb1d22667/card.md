# ZT-1a1fb1d22667 -- saml: Support full_name sync upon login.

- lang: py   issue: #34071   tier: B
- fix: https://github.com/zulip/zulip/commit/1a1fb1d22667174ca8589e264ff27fd065f2f875
- f2p: zerver.tests.test_auth_backends.SAMLAuthBackendTest.test_social_auth_full_name_sync, zerver.tests.test_auth_backends.SAMLAuthBackendTest.test_social_auth_group_sync
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Real, plausibly-assigned auth feature (SAML full_name sync via SOCIAL_AUTH_SYNC_ATTRS_DICT). The hidden test grades observable outcomes deterministically: full_name updated in DB when configured, unchanged when not configured, and unchanged with a warning on invalid input. It would fail before the change and pass after. The one exact-string assertion is a single short, deterministic log line tied directly to the new behavior (validation failure path), not a snapshot or incidental-format pin, so it is not brittle."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The existing SOCIAL_AUTH_SYNC_ATTRS_DICT setting (keyed by realm subdomain, then backend name, e.g. \"saml\") gains a new supported key `full_name` whose value is the boolean True to enable syncing; when set, an existing user's Zulip full name is updated on each social-auth login to the name provided by the IdP via the standard name attributes (no extra_attrs configuration needed).",
    "When `full_name` sync is not configured (key absent or SOCIAL_AUTH_SYNC_ATTRS_DICT empty), login must succeed as before and the user's full name must NOT be changed, even if the IdP supplies a different name.",
    "When the IdP-provided name fails Zulip's standard full-name validation (e.g. contains disallowed characters), login must still succeed and the user's name must remain unchanged; the failure is reported only via a backend-logger WARNING with the exact wording: \"Failed to sync full_name for user <user_id>: <validation error message>\" (for invalid characters the validation message is the existing \"Invalid characters in name!\").",
    "On a successful full-name sync during login, the auth backend must emit a log record at INFO level (or higher) noting the name update."
  ],
  "reason": "The test drives everything through pre-existing surfaces (SAML login flow, the SOCIAL_AUTH_SYNC_ATTRS_DICT setting, the UserProfile.full_name field, backend logger output). The only new bindings are the `full_name: True` settings key, the no-sync-when-unconfigured behavior, and the exact WARNING wording plus an INFO-level log on success \u2014 all settings/user-visible/operator-facing contract that a ticket would legitimately pin. No private helper names, internal call signatures, or mock targets are asserted (social_auth_sync_user_attributes' new parameter is never referenced by the test), so with the listed contract in the brief the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the motivation (keep display name in sync with IdP on login), and the expected-behavior evidence plus interface requirements pin down a determinate, checkable outcome: the exact setting shape (SOCIAL_AUTH_SYNC_ATTRS_DICT with a full_name: True key per subdomain/backend), the update-on-login behavior for existing users, the no-op behavior when unconfigured, the exact WARNING wording and unchanged-name behavior on validation failure, and the INFO log on success. Two engineers working from this brief would produce compatible implementations."
}
