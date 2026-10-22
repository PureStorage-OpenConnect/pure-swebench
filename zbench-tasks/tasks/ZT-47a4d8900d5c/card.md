# ZT-47a4d8900d5c -- api-docs: Update placeholder for curl user basic auth credentials.

- lang: py   issue: #479   tier: B
- fix: https://github.com/zulip/zulip/commit/47a4d8900d5c4bc006675422e09a2e53aea2f910
- f2p: zerver.tests.test_markdown.MarkdownErrorTests.test_curl_code_block_validation, zerver.tests.test_markdown.MarkdownErrorTests.test_curl_code_block_without_validation, zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_example, zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_example_with_excludes, zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_with_array_example, zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_with_default_examples, zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_with_object, zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_with_param_in_path, zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_wrapper
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior change in API-docs curl-example generator",
  "reason": "Not docs-only churn: the change modifies Python generator code (markdown_extension.py) that alters observable output \u2014 placeholder credentials in generated curl examples and a conditional auth-credentials include for secure endpoints (excluding the two insecure fetch_api_key operations). The hidden tests grade this output deterministically with clear fail-before/pass-after behavior. While the tests assert expected curl example strings, these are short (~5 line) deterministic outputs that ARE the behavior under test for a generator, not incidental long snapshots \u2014 analogous to asserting an error-message string. The exact placeholder names and include filename are spec-thin, but naming/spec gaps are explicitly deferred to later stages."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The authentication placeholder in generated curl documentation examples changes from `BOT_EMAIL_ADDRESS:BOT_API_KEY` to `EMAIL_ADDRESS:API_KEY` (email placeholder `EMAIL_ADDRESS`, API key placeholder `API_KEY`), since these examples apply to any user, not just bots.",
    "Every generated curl example for an endpoint requiring authentication must begin with the markdown include directive `{!curl-auth-credentials.md!}` followed by a blank line (i.e. the literal prefix `{!curl-auth-credentials.md!}\\n\\n`) immediately before the ```curl code fence, pulling in shared instructions on obtaining credentials.",
    "The unauthenticated API-key-fetch endpoints (POST /dev_fetch_api_key and POST /fetch_api_key) must NOT receive the `{!curl-auth-credentials.md!}` prefix; their examples still begin directly with the ```curl fence."
  ],
  "reason": "The tests bind only to user-visible documentation output: new credential placeholder strings and a markdown include directive prepended to authenticated curl examples. These are exact strings a solver cannot guess, but they are precisely the kind of content a ticket would dictate (docs wording and a named shared include file). No private helper names, internal signatures, or implementation-detail mocks are asserted \u2014 the mocked spec fixtures already existed at base. With the three contract items above in the brief, the test grades behavior, not name-guessing."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_markdown.MarkdownErrorTests.test_curl_code_block_validation",
    "zerver.tests.test_markdown.MarkdownErrorTests.test_curl_code_block_without_validation",
    "zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_example",
    "zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_with_default_examples",
    "zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_with_array_example",
    "zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_with_object",
    "zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_with_param_in_path",
    "zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_wrapper",
    "zerver.tests.test_openapi.TestCurlExampleGeneration.test_generate_and_render_curl_example_with_excludes"
  ],
  "reason": "The diff is Zulip commit 47a4d8900d5c, which changes curl auth placeholders (BOT_EMAIL_ADDRESS:BOT_API_KEY -> EMAIL_ADDRESS:API_KEY) and prepends the {!curl-auth-credentials.md!} include to generated curl examples. In test_markdown.py, the two MarkdownErrorTests hunks fall in test_curl_code_block_validation and test_curl_code_block_without_validation. In test_openapi.py, the seven TestCurlExampleGeneration hunks fall in the methods listed, mapped by each hunk's mock/endpoint (spec_mock_without_examples -> with_default_examples, spec_mock_using_object -> with_object, spec_mock_using_param_in_path -> with_param_in_path, custom api_url -> curl_wrapper, the two /messages hunks -> with_array_example and example_with_excludes) and confirmed against the upstream commit."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user-facing motivation (BOT_EMAIL_ADDRESS is misleading since the API isn't bot-only), and the expected-behavior evidence pins down the exact new placeholder text (EMAIL_ADDRESS:API_KEY), the exact literal prefix ({!curl-auth-credentials.md!} plus blank line) on authenticated examples, and the interface requirements specify the two exempt endpoints. Together these define a determinate, checkable outcome that two engineers would implement compatibly."
}
