# ZT-124a32e8194d -- compose: Save messages as drafts when window loses focus.

- lang: web   issue: #35262   tier: B
- fix: https://github.com/zulip/zulip/commit/124a32e8194da555bb3f9fb417393998e84b5b55
- f2p: web/tests/compose.test.cjs, web/tests/compose_video.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, plausibly-assigned feature (save compose draft on window blur) with a small behavior-changing diff. The hidden test grades observable behavior deterministically in Zulip's node test harness: it stubs window via to_$ overrides, which (per zjsunit's unused-override enforcement and the handler wiring in compose_setup.initialize) fails before the fix and passes after, since the blur handler registration on $(window) is the new observable effect. No exact-string pinning, no HTML/JSON snapshots, no version/time gating \u2014 just event-handler wiring checks, which are stable and deterministic."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When the window loses focus, the user's in-progress compose draft must be saved so no work is lost (window 'blur' saves the current draft).",
    "This blur handler must be registered as part of compose setup initialization \u2014 i.e., inside the existing compose_setup.initialize() entry point, which callers invoke once at startup.",
    "The handler must be attached through the codebase's standard jQuery event mechanism on the window object ($(window).on(\"blur\", ...)), not a raw window.addEventListener call."
  ],
  "reason": "The hidden test makes no direct assertions about the new feature; it only adds window.to_$ stubs so existing compose tests survive the new handler. But because zjsunit fails tests whose non-noop function overrides go unused, those stubs implicitly require that compose_setup.initialize() invoke $(window) \u2014 pinning both the registration site (an existing public entry point) and the mechanism (jQuery wrapping of window). Neither is user-visible behavior, so not 'clean', but both are one-line requirements a ticket could state, and no invented internal names are referenced, so a brief cures it."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the goal clearly (save the in-progress draft in a window blur handler), and the interface requirements pin down the observable contract: registration inside compose_setup.initialize(), attachment via $(window).on(\"blur\", ...), and the effect of saving the current draft. Together these give a determinate, checkable outcome that two engineers would implement compatibly."
}
