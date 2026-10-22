# ZT-46b1708ee174 -- fenced_code: Fixes fallback to plain code when Pygments fails.

- lang: py   issue: #22287   tier: B
- fix: https://github.com/zulip/zulip/commit/46b1708ee17422486477220690dcc267a32aa374
- f2p: zerver.tests.test_markdown.MarkdownErrorTests.test_fenced_code_with_pygments_exception
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned bug fix (Pygments failures should degrade to plain code blocks instead of erroring a message post). The hidden test grades observable behavior deterministically: it injects a Pygments failure via mock and asserts the message still renders with a <pre> block containing the original code text. Assertions use substring checks (assertIn) rather than pinning full rendered-HTML snapshots, so it is not format-brittle; the log-message check mirrors the fix's logging call and is stable. Clear fail-before/pass-after signal."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When Pygments raises an exception while highlighting a fenced code block, message rendering must not fail: the block must fall back to plain, HTML-escaped code wrapped in the standard <pre>/<code> markup (preserving the language class and the original code text), exactly as if no highlighting language were usable.",
    "The highlighting failure must be logged at ERROR level (with exception traceback) using a message containing the phrase 'Failed to highlight fenced code block'.",
    "Fenced-code highlighting must still be attempted through the existing CodeHilite.hilite mechanism used by zerver.lib.markdown.fenced_code; the fallback engages only when that call raises."
  ],
  "reason": "The test exercises behavior almost entirely through pre-existing surface: markdown_convert and its rendered_content are existing APIs, and the mock target zerver.lib.markdown.fenced_code.CodeHilite.hilite already exists at the base commit (the base code calls highliter.hilite()), so no internal name invented by the fix is being patched. The output assertions (<pre> present, code text preserved) check user-visible fallback behavior. The only new bindings are the ERROR log level and the log-message phrase 'Failed to highlight fenced code block' (checked as a substring, not exact wording). A log message and its level are legitimate product-spec material for an error-handling ticket \u2014 handed these requirements in a brief, a solver would be graded on correctness rather than guessing \u2014 so this is specifiable rather than coupled. The requirement that hilite still be called is the natural minimal-fix shape (wrap the existing call in a try/except), not an arbitrary internal choice, but it is stated in the contract since assert_called would fail a fix that bypassed CodeHilite entirely."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the failure mode (Pygments exception \u2192 400 on message post) and the desired remedy (catch, log, fall back to unhighlighted rendering). The evidence pins down the observable contract precisely: fallback output keeps <pre> markup and original code text, the error is logged at ERROR level with the phrase 'Failed to highlight fenced code block', and highlighting still flows through CodeHilite.hilite in zerver.lib.markdown.fenced_code. Together these make the outcome determinate and independently checkable."
}
