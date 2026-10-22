# ZT-6586d9078ea4 -- copy_and_paste: Paste Excel copied content as image and text.

- lang: web   issue: #32968   tier: B
- fix: https://github.com/zulip/zulip/commit/6586d9078ea4c12187cef6dba8a4a801a2d89b0b
- f2p: web/tests/copy_and_paste.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix / behavior restoration",
  "reason": "The change restores real user-facing behavior (Excel clipboard HTML is detected so Ctrl+V pastes as image while Ctrl+Shift+V pastes formatted text), a plausible assigned workflow tied to a labeled issue. The hidden test grades observable outcomes deterministically: is_single_image() must return true for a realistic Excel clipboard fixture (fails before, passes after), and paste_handler_converter() must yield a short expected text conversion. The long HTML blob is test *input*, not a pinned snapshot assertion; the asserted outputs are a boolean and a brief deterministic string consistent with the existing test style, so it is not format-over-behavior brittleness."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The `copy_and_paste` module exports a public function `is_single_image(paste_html: string): boolean` that reports whether pasted clipboard HTML should be treated as an image paste (previously an internal check for a lone <img> element; callers use it to decide between image-paste and formatted-text-paste on plain Ctrl+V).",
    "`is_single_image` must return true for clipboard HTML originating from Microsoft Excel (Office/Excel clipboard export: Excel ProgId/Generator metadata, Office namespaces, xl-prefixed cell classes, StartFragment markers), so that a plain paste of Excel cells is inserted as an image rather than converted text.",
    "Pasting Excel clipboard HTML with paste-as-plain-formatting (Ctrl+Shift+V) must continue to route through the existing `paste_handler_converter`, yielding the cell text content as formatted text."
  ],
  "reason": "The second assertion exercises `paste_handler_converter`, a pre-existing exported API, and its expected output ('$ 20.00', '$ 7.00' lines) falls out of the unchanged conversion pipeline rather than any new author choice. The only new binding is `is_single_image` being exported with true-for-Excel semantics. The name already exists at the base commit (as a private helper), and its promotion plus the Excel-detection semantics are exactly what a product brief would dictate ('Excel pastes should be treated as image pastes on plain paste'); given those requirements, the test grades correctness of behavior, not name-guessing. Notably, the test does not bind to the internal helper `is_from_excel`, its signature, or any detection-heuristic details, which remain free implementation choices."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user-visible regression (Excel paste lost its image form), the evidence pins down the exact observable contract \u2014 Excel clipboard HTML must be classified as an image paste on Ctrl+V while Ctrl+Shift+V still converts it to text via paste_handler_converter \u2014 and the interface requirements name the exact public export (is_single_image) and its semantics. Together these give a determinate, independently checkable outcome."
}
