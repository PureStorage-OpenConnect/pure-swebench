# Add an `OIDC_REQUIRE_LIMIT_TO_SUBDOMAINS` server setting mirroring the existing SAML equivalent

## Background

Zulip supports authentication via OpenID Connect through the `GenericOpenIdConnectBackend` class. Server administrators configure one or more OIDC identity providers in the `SOCIAL_AUTH_OIDC_ENABLED_IDPS` setting, a dict mapping an IdP name (e.g. `"testoidc"`) to a dict of options for that IdP. One of the supported per-IdP options is `limit_to_subdomains`, a list of realm subdomains that the IdP is allowed to authenticate users for.

For SAML authentication, Zulip already has a server setting `SAML_REQUIRE_LIMIT_TO_SUBDOMAINS`: when enabled, every configured SAML IdP is required to declare `limit_to_subdomains`, and IdPs that fail to do so are rejected at backend initialization time with an error logged. This is a hardening feature for multi-realm servers, ensuring no IdP can accidentally be usable across all realms.

## Current behavior

No equivalent protection exists for OIDC. There is no setting that forces OIDC IdPs configured in `SOCIAL_AUTH_OIDC_ENABLED_IDPS` to declare `limit_to_subdomains`; an IdP configured without it is silently valid for every realm on the server.

## Required behavior

Add a new boolean server setting `OIDC_REQUIRE_LIMIT_TO_SUBDOMAINS`, defaulting to `False`, that behaves analogously to `SAML_REQUIRE_LIMIT_TO_SUBDOMAINS` but for OIDC:

1. When the setting is `False` (the default), behavior is unchanged from today.
2. When the setting is `True`, every IdP configured in `SOCIAL_AUTH_OIDC_ENABLED_IDPS` must specify the `limit_to_subdomains` option to be considered valid.
3. Validation happens when the `GenericOpenIdConnectBackend` is initialized (i.e. instantiating the backend triggers a validation pass over the configured IdPs). Any IdP that does not specify `limit_to_subdomains` is removed from `SOCIAL_AUTH_OIDC_ENABLED_IDPS`, so that only compliant IdPs remain active and usable for login. Compliant IdPs (those that do specify `limit_to_subdomains`) must be left fully intact and functional.
4. For each validation pass that finds one or more non-compliant IdPs, exactly one ERROR-level message must be emitted on the backend's authentication logger (the same logger used for other auth-backend log output), with exactly this wording:

   ```
   OIDC_REQUIRE_LIMIT_TO_SUBDOMAINS is enabled and the following IdPs don't have limit_to_subdomains specified and will be ignored: <list>
   ```

   where `<list>` is the Python list rendering of the offending IdP names, e.g. `['testoidc']`. If all configured IdPs are compliant, no such error is logged and nothing is removed.

### Example

With `OIDC_REQUIRE_LIMIT_TO_SUBDOMAINS = True` and two IdPs configured — `testoidc` without `limit_to_subdomains` and `testoidc2` with `limit_to_subdomains: ["zulip"]` — instantiating `GenericOpenIdConnectBackend` must:

- remove `testoidc` from `SOCIAL_AUTH_OIDC_ENABLED_IDPS`, leaving only `testoidc2`;
- log one ERROR: `OIDC_REQUIRE_LIMIT_TO_SUBDOMAINS is enabled and the following IdPs don't have limit_to_subdomains specified and will be ignored: ['testoidc']`.

## Interface requirements

- A new boolean server setting `OIDC_REQUIRE_LIMIT_TO_SUBDOMAINS` (default `False`), analogous to the existing `SAML_REQUIRE_LIMIT_TO_SUBDOMAINS`: when `True`, every IdP configured in `SOCIAL_AUTH_OIDC_ENABLED_IDPS` must specify the pre-existing `limit_to_subdomains` option to be considered valid.
- When `OIDC_REQUIRE_LIMIT_TO_SUBDOMAINS` is enabled, initialization of the pre-existing OIDC backend class `GenericOpenIdConnectBackend` validates the configured IdPs and removes every non-compliant IdP from `SOCIAL_AUTH_OIDC_ENABLED_IDPS`, so that only IdPs with `limit_to_subdomains` remain active; compliant IdPs are unaffected.
- For each such validation pass that finds non-compliant IdPs, exactly one ERROR-level message is emitted on the backend's auth logger with the wording: `OIDC_REQUIRE_LIMIT_TO_SUBDOMAINS is enabled and the following IdPs don't have limit_to_subdomains specified and will be ignored: <list>`, where `<list>` is the Python-list rendering of the offending IdP names (e.g. `['testoidc']`).

## Notes

- Follow the existing pattern used by `SAML_REQUIRE_LIMIT_TO_SUBDOMAINS` for where the setting is declared (default settings module) so it can be overridden in server configuration like any other auth setting.
- The new setting should also be documented alongside the other OIDC configuration options in the server's authentication settings template/documentation, consistent with how the SAML equivalent is presented.
