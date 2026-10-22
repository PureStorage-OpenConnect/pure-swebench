# ZT-136be83502b0 -- mentions: Warn on non-silent group mentions with unsubscribed members.

- lang: web   issue: #33545   tier: B
- fix: https://github.com/zulip/zulip/commit/136be83502b04956c51789361ddc43b21bd8986a
- f2p: web/tests/composebox_typeahead.test.cjs
- p2p: web/tests/compose_validate.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, plausibly-assigned frontend feature: warn when a non-silent group mention targets a group with no active subscribed members in the channel. The behavior is observable and deterministic (a new warning banner with a distinct classname appended on typeahead selection, gated on silence, stream context, and recursive membership/subscription checks), which Zulip's node-based web tests can grade via fail-before/pass-after assertions on the banner logic. The visible test diff is just mock plumbing in an existing suite (truncated), with no signs of brittle exact-string or snapshot pinning. None of the drop criteria (rename, revert, docs, i18n churn, version-gating, CSS-only) apply."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The compose_validate module gains an exported function `warn_if_mentioning_unsubscribed_group(mentioned_group, $textarea, is_silent)`, mirroring the existing `warn_if_mentioning_unsubscribed_user`; when a user selects a user-group mention from the compose typeahead into a channel compose box (non-silent), callers invoke it to show a warning banner if no active member of the group (including recursive subgroup members) is subscribed to that channel.",
    "The compose_validate module gains an exported `initialize()` function that registers its one-time UI event handlers (the click handler opening the group info popover from the warning banner's group pill); it is called once during application startup alongside the other compose modules' initialize calls."
  ],
  "reason": "The test asserts no new behavior; it only requires that compose_validate expose two new named exports (`warn_if_mentioning_unsubscribed_group`, `initialize`) callable from composebox_typeahead. compose_validate is a pre-existing module whose exports are the established public surface for compose warnings (the direct sibling `warn_if_mentioning_unsubscribed_user` already exists and is already mocked at base), so a ticket could legitimately dictate both names, the module placement, and the call sites. With those two contract items in the brief, the hidden test grades correct wiring rather than name-guessing. No internal helpers, data-structure fields, or invented module layout are pinned."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue plus the interface requirements fully determine the observable outcome: the trigger condition (non-silent group mention in a channel compose with no active recursive member subscribed), the exact banner copy, styling, absence of buttons, the popover click behavior, and the two exported entry points (warn_if_mentioning_unsubscribed_group and initialize) with their call sites. Two engineers working from this brief would produce compatible implementations."
}
