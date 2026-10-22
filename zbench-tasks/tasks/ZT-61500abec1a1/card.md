# ZT-61500abec1a1 -- compose_paste: Add turndown rule for divs to avoid extra newlines.

- lang: web   issue: #36936   tier: B
- fix: https://github.com/zulip/zulip/commit/61500abec1a10cf8601324dbad0cd6348ad9d0ac
- f2p: web/tests/compose_paste.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real bug fix (extra newlines when pasting div-wrapped HTML from VS Code) with a deterministic hidden test: it feeds a representative HTML paste payload into paste_handler_converter and asserts the converted markdown output. The assertion targets exactly the observable behavior the fix changes (single vs. doubled newlines), fails before and passes after the patch, and is a short expected string rather than a fragile snapshot or format-pinning check."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test invokes `compose_paste.paste_handler_converter`, a pre-existing exported function already exercised by adjacent tests at the base commit (e.g. the Etherpad and Google Sheets cases in the same run_test block). The new assertion only checks user-visible behavior: given VS Code-style clipboard HTML where each line is a <div>, the converted markdown has single newlines between lines instead of blank lines. It binds to no new names \u2014 not the turndown rule name ('no extra newline'), not any helper, mock, or internal structure introduced by the fix. Any correct implementation of 'pasting div-wrapped lines should not insert extra newlines' passes; no author-only knowledge is required."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives clear reproduction steps and environment, and the evidence supplies the exact HTML clipboard shape VS Code produces plus the exact required output, so a determinate, checkable outcome (single newlines between div-wrapped lines) can be stated along with non-regression constraints for existing paste sources."
}
