# ZT-e8364d8edd79 -- integrations: Fix jotform integration to receive files.

- lang: py   issue: #32460   tier: B
- fix: https://github.com/zulip/zulip/commit/e8364d8edd791b4b3a917978d249bbc3d2798820
- f2p: zerver.webhooks.jotform.tests.JotformHookTests.test_response
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, assignable engineering task: the Jotform webhook broke on payloads containing file uploads, and the fix adds parsing of rawRequest/temp_upload to render file links. The hidden test grades observable behavior deterministically \u2014 a fixed multipart fixture is posted to the webhook endpoint and the resulting Zulip message body is checked. Asserting the exact message content is the standard Zulip webhook-test pattern and is not incidental formatting: the message text (including the markdown file links) IS the behavior the fix changes, the fixture is static, and the test fails before / passes after. No time/version gating, no snapshot of unrelated output."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When a Jotform submission includes file-upload questions, the webhook message must render each file-upload answer as Markdown links: for each uploaded file, `[<filename>](<file URL>)` where the link text is the filename as shown in the submission's pretty-printed answer and the URL is the corresponding uploaded-file URL from the submission payload (matched by URL-decoded filename); multiple files for one question are joined with a comma and a space.",
    "Each file-upload question's bullet line in the message must be preceded by a blank line (so uploaded images render correctly in Zulip); non-file questions remain consecutive bullets with no blank lines between them.",
    "File-upload answers must be recognized as the trailing entries of the payload's pretty-printed field list (file-upload questions always appear last there), including filenames that contain spaces and special characters.",
    "Question labels ending in `?` are rendered as `* **<label>** <value>` (space separator, no colon), while all other labels use `* **<label>**: <value>` \u2014 pre-existing behavior that the new expected message continues to exercise."
  ],
  "reason": "The test drives only the pre-existing webhook endpoint and asserts the user-visible Zulip message, so no internal helper names, mock targets, or module layout are bound (the new functions format_uploaded_file_links / is_non_file_upload_question_with_response are never referenced by the test). However, the expected message pins new output-formatting choices a solver could not independently guess \u2014 comma-separated Markdown links with the pretty-field filename as link text and the payload upload URL as target, plus a blank line inserted before each file-upload bullet. These are user-facing message-format decisions a ticket would legitimately dictate; handed this contract, the test grades correctness of behavior rather than name-guessing."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.webhooks.jotform.tests.JotformHookTests.test_response"
  ],
  "reason": "The diff modifies the expected message in the sole test method of JotformHookTests (the one calling self.check_webhook(\"response\", ...)), which in Zulip's jotform webhook tests is test_response; the fixture change (response.multipart) is exercised by this same test."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the failure mode (handler assumes JSON, Jotform sends multipart/form-data), and the expected-behavior evidence provides a complete concrete payload (pretty string plus rawRequest upload-URL lists) together with the exact required rendered message, including the blank-line rule, the link format, filename-with-special-characters matching, and the '?' label formatting. That is enough to state a determinate, checkable outcome that two engineers would implement compatibly."
}
