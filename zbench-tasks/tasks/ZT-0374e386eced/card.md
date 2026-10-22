# ZT-0374e386eced -- compose_paste: Avoid pasting URLs when pasting a single image.

- lang: web   issue: #36156   tier: B
- fix: https://github.com/zulip/zulip/commit/0374e386ecedfcd83640743a9270f906c351aca8
- f2p: web/tests/compose_paste.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real user-reported bug (Chrome image paste misclassified as URL) fixed by changing is_single_image logic in compose_paste.ts. The hidden test adds a deterministic behavioral assertion \u2014 assert.ok(is_single_image(input)) on a representative Chrome-style paste fragment with comment/whitespace nodes \u2014 which fails before the fix and passes after. No snapshot pinning, formatting dependence, or nondeterminism."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test adds one new input case to an existing test of `compose_paste.is_single_image`, an exported function that already exists at the base commit (the code diff modifies its body, not its name or signature). The assertion is purely behavioral: a pasted HTML fragment containing a single <img> plus surrounding whitespace text nodes and comment nodes must classify as a single image. The test never references the fix's internal choices \u2014 the new private helper `count_valid_text_nodes_upto`, the querySelectorAll approach, or any internal data structures \u2014 so any correct implementation of the behavior passes."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives clear reproduction steps and the expected product behavior (upload clipboard image data instead of inserting the URL), and the evidence pinpoints the exact failing input shape: Chrome's HTML clipboard fragment with StartFragment/EndFragment comment nodes and whitespace-only text nodes around a lone <img>. Together these determine a concrete, checkable outcome: is_single_image must treat comment nodes and empty text nodes as ignorable, while all previously handled payloads keep their classification."
}
