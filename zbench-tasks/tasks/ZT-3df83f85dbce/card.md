# ZT-3df83f85dbce -- webhooks: Rebrand HelloSign integration as Dropbox Sign.

- lang: py   issue: #30779   tier: B
- fix: https://github.com/zulip/zulip/commit/3df83f85dbcec7471e1c5b9bd9b807ac33ffc7c1
- f2p: zerver.webhooks.dropboxsign.tests.DropboxSignHookTests.test_legacy_urls, zerver.webhooks.dropboxsign.tests.DropboxSignHookTests.test_signatures_message
- p2p: zerver.tests.test_integrations

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior-affecting refactor (integration rebrand with legacy URL support)",
  "reason": "Not a pure rename: the change introduces a new /api/v1/external/dropboxsign endpoint plus a legacy_names mechanism keeping the old hellosign URL functional. The hidden test grades observable behavior deterministically \u2014 posting fixture payloads to both the new and legacy webhook URLs and asserting the resulting topic and short message content (standard Zulip WebhookTestCase pattern, not a snapshot or exact-long-string pin). It fails before the fix (dropboxsign endpoint and legacy alias don't exist) and passes after, so it's outcome-verifiable. This is a realistic assigned engineering task, as evidenced by the 'help wanted' issue."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The HelloSign incoming webhook integration is renamed to the slug `dropboxsign` (display name \"Dropbox Sign\"): its webhook endpoint becomes /api/v1/external/dropboxsign, and per Zulip's existing webhook framework convention its module and fixtures live under zerver/webhooks/dropboxsign/.",
    "Webhook URLs using the old slug `hellosign` (/api/v1/external/hellosign) must continue to be accepted and routed to the renamed integration, by registering `hellosign` in the integration's legacy_names (a registration mechanism that already exists at the base commit).",
    "The integration's message-formatting behavior is unchanged by the rename: the same signature-request payloads produce the same topic (document title, e.g. the signature request's title) and the same notification message text as before."
  ],
  "reason": "The test binds only to the new integration slug `dropboxsign` and to continued support of the legacy `hellosign` URL \u2014 both classic ticket-level contract for a rebrand task. The supporting machinery (IncomingWebhookIntegration.legacy_names, build_webhook_url's legacy_name support, and the api_{name}_webhook module convention) pre-exists at the base commit (verified: upstream commit 3df83f85 touches neither test_classes.py nor the class definition). Message wording and fixtures are unchanged pre-existing behavior, and the fixtures ship with the test. No private helper names, mock targets, or invented internal structure are asserted."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives the intent (HelloSign rebranded to Dropbox Sign), the evidence establishes the concrete observable outcomes (new slug/directory dropboxsign, legacy hellosign URL still routed, identical topic and message text including an exact example), and the interface requirements pin the names. Together these determine a checkable outcome that two engineers would implement compatibly."
}
