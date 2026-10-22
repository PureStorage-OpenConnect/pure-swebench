# ZT-be5c81286cc4 -- rendered_markdown: Offset ordered lists by start and count.

- lang: web   issue: #33424   tier: B
- fix: https://github.com/zulip/zulip/commit/be5c81286cc4f60bcafdc78d47c1337a56af1bdf
- f2p: web/tests/postprocess_content.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real bug fix (3+ digit ordered lists cut off) with a deterministic hidden test that fails before and passes after. The test asserts a short, targeted transformation \u2014 that postprocess_content adds the correct counter-length-N class to an <ol> given its start attribute and item count \u2014 not a long snapshot or incidental formatting. The one-line input/output equality on a tiny HTML fragment directly grades the observable behavior the fix introduces."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "postprocess_content (the pre-existing HTML postprocessing entry point) adds a CSS class of the form `counter-length-<N>` to every `<ol>` element in the rendered message content",
    "`<N>` is the number of decimal digits in the largest list-item counter value, computed as (the ol's `start` attribute, defaulting to 1 when absent) + (number of child items) - 1; e.g. start=9 with 2 items gives max counter 10, so class `counter-length-2`",
    "the class is appended to the ol's existing attributes; the `start` attribute and list contents are otherwise preserved unchanged"
  ],
  "reason": "The test drives the pre-existing public function postprocess_content with plain HTML input and asserts on its HTML output, so no internal helpers, mocks, or private structures are touched. The only new binding is the `counter-length-<N>` class name and its digit-count semantics \u2014 a CSS hook on user-visible DOM output, equivalent to a DOM id/class a design spec would legitimately dictate for the accompanying CSS to target. Given a brief stating the class-name scheme and the max-counter digit computation (including the default start of 1), the test grades correct behavior rather than name-guessing. It is not 'clean' because the class name and its formula are new surface that did not exist at the base commit."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue clearly describes the observable bug (3+ digit ordered-list markers clipped by a fixed margin in preview and sent messages), and the evidence plus interface requirements pin down a determinate, checkable mechanism: postprocess_content must tag each <ol> with counter-length-<N> computed from start + item count - 1, preserving other attributes. Two engineers working from this brief would produce compatible implementations."
}
