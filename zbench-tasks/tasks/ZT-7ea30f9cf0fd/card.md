# ZT-7ea30f9cf0fd -- home: Add /llms.txt endpoint for LLM web-public discoverability.

- lang: py   issue: #38686   tier: B
- fix: https://github.com/zulip/zulip/commit/7ea30f9cf0fdc5edb099f8c4a0116b26bfdafc6c
- f2p: zerver.tests.test_home.HomeTest.test_home_fallback_llms_comment_when_not_web_public, zerver.tests.test_home.HomeTest.test_home_has_llms_comment_when_web_public, zerver.tests.test_home.HomeTest.test_realm_authentication_methods, zerver.tests.test_llms_txt.LlmsTxtTest.test_llms_txt_lists_only_web_public_channels, zerver.tests.test_llms_txt.LlmsTxtTest.test_llms_txt_no_web_public_streams, zerver.tests.test_llms_txt.LlmsTxtTest.test_llms_txt_spectator_access_disabled, zerver.tests.test_llms_txt.LlmsTxtTest.test_llms_txt_with_web_public_streams
- p2p: zerver.tests.test_urls

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, plausibly-assigned feature (serve /llms.txt for web-public discoverability) with a deterministic outcome-based grader: tests assert status codes (200/404 by realm setting and stream presence), content-type, and key substrings (endpoint path, narrow operator, channel names listed, private streams excluded) rather than pinning the full rendered document. The home-page tests check for short marker phrases in the HTML comment, which is a spec-gap/naming concern for later stages, not a whole-output snapshot. Not in any drop category."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The server gains a new endpoint GET /llms.txt (per the llms.txt convention, https://llmstxt.org/) that responds 200 with Content-Type text/plain and a body that begins with a markdown '#' heading.",
    "GET /llms.txt must return 404 when the realm does not have web-public stream access enabled (spectator access disabled).",
    "GET /llms.txt must return 404 when web-public access is enabled but the realm has zero web-public channels.",
    "The /llms.txt body must document how to fetch messages without authentication via the existing GET /json/messages API, explicitly mentioning that the narrow must include the 'channels' operator with operand 'web-public'.",
    "The /llms.txt body must list the realm's web-public channels by name, and must not list channels that are not web-public (private or ordinary public channels are excluded).",
    "The homepage HTML (both the logged-in app and the spectator/logged-out view) must include a comment addressed to AI agents containing the literal phrase 'AI assistant:'.",
    "When the realm has web-public streams enabled, that homepage comment must reference '/llms.txt'; when web-public streams are not enabled, the page must not mention '/llms.txt' and the comment must instead state that the organization 'does not have web-public channels' (that exact phrase appears in the HTML)."
  ],
  "reason": "All new bindings are legitimately dictated contract surface: a spec-defined well-known URL (/llms.txt), its status-code behavior (404 when web-public access is off or no web-public channels exist), content-type, and content requirements (llms.txt '#'-heading format, documenting the pre-existing /json/messages API with the pre-existing 'channels'/'web-public' narrow operator, listing only web-public channel names \u2014 'Rome' and 'Scotland' are pre-existing test fixtures, not invented names). The homepage assertions pin two user-facing literal phrases ('AI assistant:', 'does not have web-public channels'), which a ticket would legitimately specify, analogous to pinned user-facing messages. The test never binds to the fix's internal choices: it does not reference the new zerver/views/llms_txt.py module, the llms_txt view name, or the 'has_web_public_streams' template variable \u2014 everything is checked through HTTP responses. The digest-test change mocks zerver.lib.digest.enough_traffic and send_future_email, both of which exist at the base commit (it merely stabilizes an existing test against the traffic threshold), so it introduces no new coupling."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives the motivation and both proposed mechanisms (llms.txt plus a homepage pointer), and the interface requirements pin down determinate, checkable outcomes: exact endpoint path, status codes per realm state, required literal strings in the body and homepage HTML, and the channel-listing inclusion/exclusion rule. Two engineers working from this brief would produce compatible implementations."
}
