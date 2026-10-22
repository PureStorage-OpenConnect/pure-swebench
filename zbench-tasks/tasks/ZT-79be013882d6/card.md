# ZT-79be013882d6 -- compose: Remove extra blank line before lists.

- lang: web   issue: #32607   tier: B
- fix: https://github.com/zulip/zulip/commit/79be013882d64112c69f825e73591c293ae15589
- f2p: web/tests/compose_ui.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior change (UI formatting logic)",
  "reason": "Real compose-box formatting behavior change with a deterministic hidden test that asserts observable textarea state before/after formatting. The assertions are short, targeted strings representing the behavior under test (blank-line insertion around lists), not brittle long-output or snapshot pins \u2014 the test fails before the fix and passes after."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test calls the pre-existing public API compose_ui.format_text via the existing textarea-state test harness and asserts only the user-visible formatting output (blank line no longer inserted before a bulleted/numbered list, still inserted after). It binds to no new identifiers, settings, fields, or internal helpers \u2014 only the behavioral outcome the task itself defines \u2014 so a solver implementing the described fix passes without guessing any author-specific names."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the intent (drop the leading blank line, keep the trailing one), and the expected-behavior evidence pins down exact before/after textarea states and selection positions for both toggling on (numbered) and toggling off (bulleted) with surrounding content, making the outcome determinate and checkable."
}
