# ZT-733ab5f2f8c5 -- reactions: Remove emoji container when reaction count is 0.

- lang: web   issue: #32983   tier: B
- fix: https://github.com/zulip/zulip/commit/733ab5f2f8c5abfa84cd8ad0e4a5649cf51e5faf
- f2p: web/tests/reactions.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real bug fix with observable behavior: removing the last reaction previously left an empty .message_reaction_container in the DOM, pushing the add-emoji button to the next line. The hidden test grades the outcome deterministically \u2014 it asserts the outer container (not just the inner reaction element) gets removed \u2014 which fails before the fix and passes after. No snapshot pinning or format brittleness; the test stubs jQuery structure and checks the removal call."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When the last user removing their reaction brings an emoji's reaction count to zero, the UI must remove the reaction's entire outer wrapper element \u2014 the reaction element's immediate parent container (the `.message_reaction_container` wrapper from the message_reaction template) \u2014 from the DOM, rather than removing only the inner reaction element itself. Concretely, the removal is performed on the element obtained as the reaction element's parent, not on the reaction element."
  ],
  "reason": "The test actually REDUCES internal coupling relative to the old version: it deletes the stub of the internal helper `find_reaction` and lets the real lookup path run. What it now binds to is the DOM outcome expressed through jQuery's public API: it stubs the reaction element's `parent()` to return a container and asserts that `remove()` is invoked on that parent container instead of on the reaction element. The `.message_reaction_container` wrapper is pre-existing template structure at the base commit, so no new name must be guessed; the selector argument itself is not even asserted (the parent stub ignores it). The only thing a solver must know is the product-level requirement that the whole wrapper \u2014 the element's immediate parent \u2014 is what gets removed, which a ticket describing the empty-leftover-container bug would legitimately state. Residual risk is minor: an equivalent fix using `closest()` or a fresh container lookup instead of `parent()` would fail the stub, but given the fixed one-level template structure, 'remove the reaction element's parent container' is a specifiable requirement, not an arbitrary internal choice. Hence specifiable rather than clean (the base-commit behavior/test asserted removal of the reaction element itself) and not coupled (no private helper names, internal fields, or invented module layout are bound)."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the observable symptom clearly, and the expected-behavior evidence plus interface requirements pin down the exact fix semantics: on last-reaction removal, remove the reaction element's parent .message_reaction_container wrapper instead of the inner element. This yields a determinate, checkable outcome two engineers would implement compatibly."
}
