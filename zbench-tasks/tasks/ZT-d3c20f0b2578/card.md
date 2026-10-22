# ZT-d3c20f0b2578 -- notifications: Render emoji in desktop notifications.

- lang: web   issue: #30598   tier: B
- fix: https://github.com/zulip/zulip/commit/d3c20f0b2578ed4e4c74e9c11288f0e362a6d9bc
- f2p: web/tests/ui_util.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, high-priority bug fix (emoji shown as :name: text instead of unicode in desktop notifications) with an observable behavioral outcome. The hidden test calls convert_emoji_element_to_unicode with emoji class codepoints (including a ZWJ sequence) and asserts the exact unicode emoji produced \u2014 a deterministic, small, behavior-level assertion that fails before the fix (function didn't exist / old code returned text) and passes after. No snapshot pinning, formatting brittleness, or version gating."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The `web/src/ui_util` module gains an exported function `convert_emoji_element_to_unicode(element)` that takes a (jQuery-wrapped) rendered-emoji DOM element and returns a string: the Unicode emoji character(s) that element represents.",
    "For a non-image emoji element carrying Zulip's existing rendered-emoji class markup (`class=\"emoji emoji-<hex>[-<hex>...]\"`, hyphen-separated hexadecimal Unicode code points), the function must parse each hex code point and return them concatenated as a single string \u2014 e.g. `emoji-1f419` yields \"\ud83d\udc19\", and multi-codepoint sequences like `emoji-1f468-200d-1f373` yield the full ZWJ sequence \"\ud83d\udc68\u200d\ud83c\udf73\".",
    "For an `img` emoji element (custom/realm emoji with no Unicode equivalent), the function must return the element's `alt` text instead."
  ],
  "reason": "The test binds only to one new name: the exported function `ui_util.convert_emoji_element_to_unicode` and its element-in/string-out signature. In Zulip's frontend, exported module functions are the intended public API surface and a ticket could legitimately dictate this name and contract. The inputs the test uses (span elements with `emoji emoji-<hex codepoints>` classes) follow Zulip's pre-existing rendered-emoji markup convention at the base commit, not a choice invented by the fix, and the asserted outputs are the user-visible Unicode characters. The test does not touch the fix's private helper `extract_emoji_code_from_class`, the renamed wrapper `convert_unicode_eligible_emoji_to_unicode`, the message_notifications call site, or any internal data layout, so given the contract above a solver would be graded on correct codepoint decoding, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user-visible problem (emoji missing from desktop notifications) and the intended approach (convert to Unicode in the notification rendering pipeline). The expected-behavior evidence and interface requirements pin down the exact exported function name, module, input format (emoji-<hex>[-<hex>...] class markup, img alt fallback), and concrete input/output examples, making the outcome determinate and independently checkable."
}
