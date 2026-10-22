# ZT-ef863258c217 -- compose_paste: Remove title formatting more carefully.

- lang: web   issue: #31218   tier: B
- fix: https://github.com/zulip/zulip/commit/ef863258c2175f9037942780d30adae56c982860
- f2p: web/tests/compose_paste.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned bug fix in the web client's paste-to-markdown converter (stripping title/heading formatting from pasted HTML). The hidden test is deterministic and outcome-based: it feeds realistic copied-HTML fragments into paste_handler_converter and asserts short, behavior-defined output strings (e.g. 'James Madison', 'Abstract') that fail before the fix and pass after. The long HTML blobs are test inputs, not pinned output snapshots, so the test grades observable conversion behavior rather than incidental formatting."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "Every new assertion drives the pre-existing public entry point `compose_paste.paste_handler_converter(html_string) -> string`, which the same test file already exercises at the base commit, and checks purely user-visible paste outcomes (heading HTML from arXiv/ScienceDirect/Wikipedia/Hashnode pastes as its plain text; already-plain content is not double-converted). The test never references any of the fix's new internals (`check_multiple_text_nodes`, `has_single_textful_child_node`, `get_the_only_textful_child_content`), never stubs or mocks them, and asserts no internal data structures. The added `global.document/window/Node/HTMLElement/HTMLAnchorElement` lines are jsdom environment plumbing moved/extended in test setup, not a contract the solution must satisfy. Expected outputs are exactly the behavior a bug report would describe (pasted single headings should become unstyled plain text), so the test grades behavioral correctness through an existing interface with no new names to guess."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the user-visible bug and points at the exact code path, and the expected-behavior evidence supplies concrete input payloads with exact required outputs (arXiv/Wikipedia/ScienceDirect/Hashnode headings, plus the no-double-conversion cases), making the outcome determinate and checkable."
}
