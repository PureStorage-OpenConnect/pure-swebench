# ZT-98e14a644f3e -- markdown: Fix linkification of URLs starting with query params.

- lang: py   issue: #19778   tier: B
- fix: https://github.com/zulip/zulip/commit/98e14a644f3e73b1d178a2ed1edd95a88a9ad858
- f2p: zerver.tests.test_markdown.MarkdownFixtureTest.test_markdown_fixtures
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real bug fix (URLs with query strings but no path weren't linkified) with a deterministic hidden grader: the added fixture cases assert the rendered markdown output for specific inputs, which is exactly the observable behavior the fix changes. The expected HTML snippets are short, targeted, and fail-before/pass-after \u2014 this is Zulip's standard markdown test harness, not an incidental whole-page snapshot. Trailing-punctuation cases (e.g. 'https://google.com?') also directly exercise the new regex logic."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test adds cases to the pre-existing markdown fixture harness and asserts only user-visible rendering output (input text -> HTML). It binds to no new names or internal structures; the asserted behaviors (linkify URLs with query strings but no path, exclude trailing '?', ')', and '.' punctuation) are the bug report itself, checked through an interface that exists at the base commit."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_markdown.MarkdownFixtureTest.test_markdown_fixtures"
  ],
  "reason": "The diff only edits zerver/tests/fixtures/markdown_test_cases.json, appending four entries to the linkify_tests array (URL linkification cases with query strings, trailing punctuation, and parentheses). That fixture file is consumed in zerver/tests/test_markdown.py by MarkdownFixtureTest.test_markdown_fixtures, which loads both format_tests and linkify_tests via load_markdown_tests() and iterates over every linkify entry, so it is the single test target exercising the new cases. (On older Zulip checkouts the same method lives on the MarkdownTest class: zerver.tests.test_markdown.MarkdownTest.test_markdown_fixtures.)"
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue is thin (the example URL was stripped from the body), but the expected-behavior evidence pins down a determinate, checkable outcome: URLs of the form scheme://host?query must be auto-linkified, with query string included in the link and trailing '?', '.', and ')' treated as punctuation. Concrete input/output pairs plus a non-regression case make independent implementations converge."
}
