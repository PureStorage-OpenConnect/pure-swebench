# ZT-57c07bcf030d -- slack_integration: Avoid showing sender username.

- lang: py   issue: #36090   tier: B
- fix: https://github.com/zulip/zulip/commit/57c07bcf030d95f7abf3472c3b8e52f725d66533
- f2p: zerver.webhooks.slack.tests.SlackWebhookTests.test_message_with_channel_and_user_mentions, zerver.webhooks.slack.tests.SlackWebhookTests.test_message_with_complex_formatted_mentions, zerver.webhooks.slack.tests.SlackWebhookTests.test_message_with_user_mentions
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned bug fix with an observable behavioral outcome: the Slack webhook shows the sender's real display name instead of their username/email. The hidden test grades this deterministically via check_webhook with mocked Slack API calls, asserting the rendered message content \u2014 exactly the behavior the fix changes. The expected strings are short, targeted message bodies (standard Zulip webhook test pattern), not long pinned snapshots or incidental formatting, so the test fails before and passes after on the actual behavior."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test exercises only pre-existing interfaces: the Slack webhook endpoint via the long-standing check_webhook harness and the pre-existing mock_slack_api_calls fixture mechanism. The diff introduces no new function names, settings, fields, or DOM/API surface \u2014 it only updates the expected user-visible message content from the sender's username/email ('supersecretemail') to their real name ('John Doe'). That expected value is exactly the user-visible outcome a ticket would state ('Slack webhook shows the sender's email/username; show their real name instead'), and 'real_name' is Slack's own external API field, not an internal choice invented by the fix. A solver told only the bug ('messages relay the Slack username instead of the person's real name') would naturally read real_name from the mocked Slack users.info payload and pass; nothing requires guessing author-private naming."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.webhooks.slack.tests.SlackWebhookTests.test_message_with_channel_and_user_mentions",
    "zerver.webhooks.slack.tests.SlackWebhookTests.test_message_with_user_mentions",
    "zerver.webhooks.slack.tests.SlackWebhookTests.test_message_with_complex_formatted_mentions"
  ],
  "reason": "The diff edits zerver/webhooks/slack/tests.py (dotted path zerver.webhooks.slack.tests, not zerver.tests.*), modifying the bodies of three test methods in SlackWebhookTests: test_message_with_channel_and_user_mentions, test_message_with_user_mentions, and test_message_with_complex_formatted_mentions. The change to the module-level USER constant ('supersecretemail' \u2192 'John Doe') affects other tests indirectly via EXPECTED_MESSAGE formatting, but only these three methods are themselves modified in the diff."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the defect and expected outcome clearly, and the behavior evidence pins down the exact observable outputs: sender prefix and inline mentions must render the Slack display name (e.g. 'John Doe') instead of the email local part, and the users:read.email scope must become unnecessary. This is a determinate, checkable outcome."
}
