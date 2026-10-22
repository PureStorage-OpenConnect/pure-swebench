# Sync a user's full name from the identity provider on social-auth login

## Background

Zulip's social authentication framework (SAML, OIDC, and other backends built on python-social-auth) already supports syncing certain user attributes from the identity provider (IdP) at login time via the `SOCIAL_AUTH_SYNC_ATTRS_DICT` server setting. That setting is a dictionary keyed by realm subdomain, then by backend name (e.g. `"saml"`), mapping to a dict describing which attributes to sync — today this is used for things like custom profile fields (via `extra_attrs`) and group membership.

Organizations that manage identity centrally (and often disallow users from editing their own display name in Zulip) want the user's Zulip full name to follow the name recorded in the IdP: when the IdP updates a user's name, the change should take effect in Zulip the next time that user logs in. Today there is no way to do this — the name supplied by the IdP is only used when the account is first created; on subsequent logins an existing user's full name is never touched.

## Required behavior

Extend `SOCIAL_AUTH_SYNC_ATTRS_DICT` to support a new key, `full_name`, in the per-backend attribute dict. For example:

```python
SOCIAL_AUTH_SYNC_ATTRS_DICT = {
    "zulip": {
        "saml": {
            "full_name": True,
        },
    },
}
```

Semantics:

1. **Sync enabled** (`"full_name": True` present for the realm/backend): on every social-auth login by an existing user, take the user's name as provided by the IdP through the backend's standard name attributes (the same name data already used when creating new accounts — no `extra_attrs` or additional IdP attribute configuration should be required) and update the user's Zulip full name to that value if it differs. The update should go through Zulip's normal name-change flow (so the change is properly recorded and propagated like any other name change), and the backend should log a record at INFO level (or higher) noting that the user's name was updated.

2. **Sync not enabled** (the `full_name` key is absent, or `SOCIAL_AUTH_SYNC_ATTRS_DICT` is empty/unset): login proceeds exactly as before and the existing user's full name must not be modified, even when the IdP supplies a different name than the one stored in Zulip.

3. **Invalid name from the IdP**: if the IdP-provided name fails Zulip's standard full-name validation (for example, it contains disallowed characters), the login itself must still succeed and the user's stored full name must remain unchanged. The failure must be reported only as a WARNING on the auth backend's logger, with exactly this wording:

   ```
   Failed to sync full_name for user <user_id>: <validation error message>
   ```

   where `<user_id>` is the numeric ID of the user and `<validation error message>` is the message produced by Zulip's existing full-name validation (for a name with disallowed characters, that message is `Invalid characters in name!`). No other warnings or errors should be emitted for this case, and the user should not see an error.

This behavior should work for the social-auth backends that flow through Zulip's common social-auth pipeline (SAML being the primary motivating case; OIDC and similar backends use the same configuration shape keyed by their backend name). Only existing users logging in are affected — account creation behavior is unchanged.

Also document the new `full_name` option wherever `SOCIAL_AUTH_SYNC_ATTRS_DICT` is described in the production settings template and authentication documentation.

## Interface requirements

- The existing `SOCIAL_AUTH_SYNC_ATTRS_DICT` setting (keyed by realm subdomain, then backend name, e.g. `"saml"`) gains a new supported key `full_name` whose value is the boolean `True` to enable syncing. When set, an existing user's Zulip full name is updated on each social-auth login to the name provided by the IdP via the standard name attributes; no `extra_attrs` configuration is needed for this.
- When `full_name` sync is not configured (key absent or `SOCIAL_AUTH_SYNC_ATTRS_DICT` empty), login must succeed as before and the user's full name must not be changed, even if the IdP supplies a different name.
- When the IdP-provided name fails Zulip's standard full-name validation (e.g. contains disallowed characters), login must still succeed and the user's name must remain unchanged; the failure is reported only via a backend-logger WARNING with the exact wording `Failed to sync full_name for user <user_id>: <validation error message>` (for invalid characters, the validation message is the existing `Invalid characters in name!`).
- On a successful full-name sync during login, the auth backend must emit a log record at INFO level (or higher) noting the name update.
