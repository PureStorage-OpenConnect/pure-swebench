# ZT-411fd9c4fe91 -- navbar: Show "Muted user" instead of muted user's name.

- lang: web   issue: #33673   tier: B
- fix: https://github.com/zulip/zulip/commit/411fd9c4fe914dcfb3a2473030b38c77ae06fe6e
- f2p: web/tests/filter.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned UI behavior fix: DM navbar should display 'Muted user' instead of a muted user's name. The hidden test grades observable outcomes deterministically \u2014 it asserts the navbar title strings ('translated: Muted user', 'joe and translated: Muted user (guest)') produced by Filter's navbar helpers for specific narrow terms. These short expected strings ARE the behavior under test, not an incidental long snapshot; the test follows the existing navbar_helpers table pattern, fails before the fix and passes after, with no reliance on formatting churn, version gating, or non-determinism."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "In the navbar title of a direct-message narrow, a participant who has been muted by the current user must be displayed as the literal (translatable) string \"Muted user\" instead of their full name.",
    "If the muted participant is a guest and the realm shows guest indicators, the displayed string must instead be \"Muted user (guest)\", replacing the usual \"{name} (guest)\" form."
  ],
  "reason": "The test exercises only pre-existing public interfaces: Filter's navbar helpers (title, is_common_narrow, zulip_icon, redirect URL) and the pre-existing muted_users module APIs (add_muted_user/is_user_muted already exist at the base commit and are used here only to set up state). The only new surface the test binds to is the exact user-facing wording of the two title strings, \"Muted user\" and \"Muted user (guest)\", which a ticket would legitimately pin as product copy. All other asserted values (icon name, redirect URLs, group-title joining like \"joe and ...\") follow pre-existing behavior for DM narrows. No private helpers, internal fields, or implementation-specific structure is referenced, so a brief stating the two strings fully specifies the task."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user-visible defect, and the expected-behavior evidence pins down every observable detail needed for a determinate outcome: exact strings (\"Muted user\", \"Muted user (guest)\"), that they are translated, behavior in both 1:1 and group DMs, the special single-string handling for muted guests versus the normal '{name} (guest)' template, and that redirect URLs, icon, and common-narrow classification are unchanged. Two engineers working from this brief would produce compatible title-generation behavior."
}
