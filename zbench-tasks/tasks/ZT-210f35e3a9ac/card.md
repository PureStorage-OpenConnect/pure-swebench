# ZT-210f35e3a9ac -- slack_integration: Process Slack `blocks` and `attachments` syntax.

- lang: py   issue: #37428   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/210f35e3a9acab3d3a5178cfa201f874963b9d43
- f2p: zerver.webhooks.slack.tests.SlackWebhookTests.test_message_from_slack_integration_bot
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavioral improvement (incoming webhook message conversion)",
  "reason": "Small, well-specified behavioral change: the Slack incoming webhook now extracts message text from Slack `blocks`/`attachments` payloads (via process_slack_block_and_attachment) instead of only the `text` field, enabling conversion of Slack integration bot messages. Observable behavior is testable through the pre-existing webhook endpoint with a fixture payload \u2014 no refactor, docs, i18n, migration, or version-gating concerns."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "The hidden test does not import or reference any symbol introduced by the fix (e.g., it never touches `process_slack_block_and_attachment`). It exercises the pre-existing Slack webhook endpoint through the existing `WebhookTestCase` harness and the same test method that already exists at base, only updating the expected message body. The assertion is on user-visible behavior: the rendered Zulip message produced from a Slack integration-bot payload containing blocks/attachments, which is exactly the previously-unsupported case flagged by the removed TODO comment. The expected text is largely a mechanical markdown conversion of the fixture's block content (links, section text, image titles), not an arbitrary error string the fix invents. Minor caveat: the test pins the exact rendered markdown, so a solver must match the reference rendering order/format, but that is behavioral output coupling inherent to Zulip webhook tests, not coupling to new interface names."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.webhooks.slack.tests.SlackWebhookTests.test_message_from_slack_integration_bot"
  ],
  "reason": "The diff modifies exactly one test method: test_message_from_slack_integration_bot in class SlackWebhookTests, located in zerver/webhooks/slack/tests.py, which maps to the dotted path zerver.webhooks.slack.tests.SlackWebhookTests.test_message_from_slack_integration_bot."
}
