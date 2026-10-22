# ZT-31a06f2ed0ce -- integrations: Refactor `get_logo_path` to make `logo_url` non-optional.

- lang: py   issue: #22582   tier: B
- fix: https://github.com/zulip/zulip/commit/31a06f2ed0ceac586859dcb074d4dee87555adb1
- f2p: zerver.tests.test_integrations.IntegrationsTestCase.test_get_bot_avatar_path, zerver.tests.test_integrations.IntegrationsTestCase.test_get_logo_path
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior-affecting refactor",
  "reason": "Despite the 'refactor' label, this changes observable behavior: get_logo_path/get_bot_avatar_path go from returning None to raising AssertionError when no logo exists, and a new fallback_logo_path mechanism is added. The hidden test grades these outcomes deterministically \u2014 it asserts specific resolved logo paths for real integrations (onyx, xkcd), fallback resolution for embedded bots, and that constructing a logo-less Integration now raises. No snapshot pinning, no exact-message assertions, no time/version gating; a pre-fix codebase fails these assertions and a correct fix passes."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "Integration.get_logo_path gains an optional parameter `fallback_logo_path: str | None = None` and now returns `str` (never None): it returns the first path that exists on disk among the integration's default SVG logo path, its default PNG logo path, and then the `fallback_logo_path` argument if one was provided.",
    "Integration.get_logo_path raises AssertionError (instead of returning None) when none of the checked logo paths exist \u2014 including when called with no fallback argument on an integration whose default logo files are absent (e.g. embedded bots or an integration that was given an explicit `logo` because it has no default-path file).",
    "Constructing an Integration whose logo cannot be resolved (no explicit `logo` argument and no default SVG/PNG logo file on disk) raises AssertionError; integrations may no longer exist without a logo.",
    "Embedded bot integrations must construct successfully despite having no per-bot logo files, by falling back to the Zulip icon at static path `images/logo/zulip-icon-128x128.png`; this fallback is applied when resolving the logo at construction time, not baked into get_logo_path's no-argument behavior."
  ],
  "reason": "The test binds only to pre-existing surface (INTEGRATIONS, EMBEDDED_BOTS, the Integration classes, get_logo_path, get_bot_avatar_path \u2014 all present at base) plus new behavior on those existing methods: a new optional `fallback_logo_path` parameter, AssertionError-on-missing-logo semantics for both get_logo_path and the constructor, and the concrete Zulip-icon fallback path for embedded bots. These are exactly the kind of API-signature and error-semantics decisions a ticket ('enforce every integration has a logo; drop the Optional returns') would legitimately dictate. The expected concrete paths (onyx.png, generated/bots/xkcd/logo.png, prometheus.png) are pre-existing repository data, not invented names. No private helpers, mock targets, or internal data-structure names are pinned, so a brief containing the listed contract lets the test grade correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the goal (guarantee logo_url for all integrations, including embedded bots), and the behavior evidence plus interface requirements pin down the concrete design actually required: get_logo_path returns str with SVG\u2192PNG\u2192fallback resolution order, raises AssertionError when nothing exists, construction asserts a resolvable logo, and embedded bots resolve via the Zulip icon fallback supplied at construction time rather than by adding per-bot logo files (the issue's suggested alternative). Concrete examples (slack_incoming, onyx, xkcd, alertmanager, converter) make the outcome determinate and independently checkable."
}
