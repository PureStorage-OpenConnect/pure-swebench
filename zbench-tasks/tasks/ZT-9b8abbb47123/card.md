# ZT-9b8abbb47123 -- oidc: Add OIDC_REQUIRE_LIMIT_TO_SUBDOMAINS setting.

- lang: py   issue: #36580   tier: B
- fix: https://github.com/zulip/zulip/commit/9b8abbb471232875cb93fdadd6dc35c2fd514eff
- f2p: zerver.tests.test_auth_backends.GenericOpenIdConnectTest.test_social_auth_oidc_idp_limited_to_subdomains_attempt_wrong_realm, zerver.tests.test_auth_backends.GenericOpenIdConnectTest.test_social_auth_oidc_require_limit_to_subdomains
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature (security setting)",
  "reason": "Real, plausibly-assigned feature extending an existing SAML setting pattern to OIDC. The hidden test grades observable behavior deterministically: non-compliant IdPs are removed from SOCIAL_AUTH_OIDC_ENABLED_IDPS (asserted via remaining keys) and an error is logged. The exact-log-message assertion follows Zulip's standard assertLogs pattern and the message is short, fully determined by the fix, and part of the feature's contract \u2014 not a brittle snapshot of incidental formatting. Test fails before the change (setting doesn't exist) and passes after."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "A new boolean server setting `OIDC_REQUIRE_LIMIT_TO_SUBDOMAINS` (default False), analogous to the existing `SAML_REQUIRE_LIMIT_TO_SUBDOMAINS`: when True, every IdP configured in `SOCIAL_AUTH_OIDC_ENABLED_IDPS` must specify the (pre-existing) `limit_to_subdomains` option to be considered valid.",
    "When `OIDC_REQUIRE_LIMIT_TO_SUBDOMAINS` is enabled, initialization of the OIDC backend (`GenericOpenIdConnectBackend`, a pre-existing class) validates the configured IdPs and removes every non-compliant IdP from `SOCIAL_AUTH_OIDC_ENABLED_IDPS`, so that only IdPs with `limit_to_subdomains` remain active; compliant IdPs are unaffected.",
    "For each such validation pass that finds non-compliant IdPs, exactly one ERROR-level message is emitted on the backend's auth logger with the wording: \"OIDC_REQUIRE_LIMIT_TO_SUBDOMAINS is enabled and the following IdPs don't have limit_to_subdomains specified and will be ignored: <list>\", where <list> is the Python-list rendering of the offending IdP names (e.g. ['testoidc'])."
  ],
  "reason": "The test touches only three new surfaces: the settings name OIDC_REQUIRE_LIMIT_TO_SUBDOMAINS, the removal of non-compliant IdPs from the SOCIAL_AUTH_OIDC_ENABLED_IDPS setting observable at backend init, and the exact operator-facing ERROR log wording. All are contract-grade: settings names and log phrasing are routinely pinned by tickets (and the codebase already has the SAML twin SAML_REQUIRE_LIMIT_TO_SUBDOMAINS to mirror), and the observable effect is asserted through pre-existing interfaces (Django settings dict and the existing GenericOpenIdConnectBackend constructor and logger channel). No private helpers, internal call signatures, or mock targets are bound. Given these requirements in a brief, the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue body is thin, but the expected-behavior evidence and interface requirements together pin down a fully determinate outcome: the setting name, its default, where validation occurs (backend __init__), the removal semantics for non-compliant IdPs, and the exact error log wording. The existing SAML_REQUIRE_LIMIT_TO_SUBDOMAINS feature in the codebase gives the engineer a concrete in-repo pattern to mirror, so two engineers would independently produce compatible implementations."
}
