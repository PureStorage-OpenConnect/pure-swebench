# ZT-93913dd6e797 -- integrations: Support colon and comma characters in jotform payloads.

- lang: py   issue: #32461   tier: B
- fix: https://github.com/zulip/zulip/commit/93913dd6e797e5c9ad6038412baee20c0481182c
- f2p: zerver.webhooks.jotform.tests.JotformHookTests.test_bad_payload, zerver.webhooks.jotform.tests.JotformHookTests.test_response_with_colon_comma_characters
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned bug fix: the Jotform webhook mis-parses payloads whose keys/values contain colons or commas. The hidden test exercises the observable outcome (the message posted from a fixed multipart fixture) deterministically, and fails-before/passes-after. Although the test compares an exact message string, that string IS the behavior under test \u2014 correct key/value extraction with colons, commas, and duplicate keys \u2014 not incidental formatting; this is the standard Zulip webhook test pattern, with deterministic fixture-driven output."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test exercises the pre-existing Jotform webhook endpoint through the standard check_webhook harness with a new fixture payload, asserting only the user-visible message content. The webhook, its URL, the '* **Key**: Value' bullet formatting, the file-link rendering (format_uploaded_file_links), and the topic-from-formTitle behavior all exist at the base commit; the expected message is fully derivable from the fixture's 'pretty'/'rawRequest' data plus that existing formatting convention. The test binds to no new function names, fields, or internal helpers introduced by the fix (get_pretty_fields, format_value are never referenced) \u2014 it only requires that keys/values containing colons and commas be parsed correctly, which is the bug itself, not an implementation choice."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the root cause (naive split on ':' and ', ' in the Jotform handler), and the example payload plus its required rendering fully determine the observable contract: topic from formTitle, exact bullet format, verbatim preservation of colons/commas in labels and values, space-joined array answers, blank-line-separated file-upload section with filename-to-URL Markdown links, exclusion of bookkeeping keys, and preservation of the existing 'Unable to handle Jotform payload' rejection. Two engineers following this brief would produce byte-identical output for the worked example."
}
