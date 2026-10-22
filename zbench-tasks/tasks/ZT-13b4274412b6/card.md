# ZT-13b4274412b6 -- slack_converter: Further reduce rich_text related conversion loss.

- lang: py   issue: #36781   tier: B
- fix: https://github.com/zulip/zulip/commit/13b4274412b611331e3fd62bec474c7969c5c067
- f2p: zerver.tests.test_slack_importer.SlackImporter.test_channel_message_to_zerver_message
- p2p: zerver.tests.test_slack_message_conversion

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned bug fix: rich_text blocks in Slack import/webhook were silently dropped, losing message content; the fix falls back to the raw text field. The hidden test grades observable behavior deterministically \u2014 it feeds a fixed Slack message payload through the converter and asserts the resulting Zulip message content and message count, which fail before the fix (content lost) and pass after. The expected-content string is the converter's direct output for the given input, not an incidental snapshot of unrelated formatting, so it is not brittle in the disqualifying sense."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test asserts only on the user-visible output of the pre-existing Slack import pipeline (message content and sender from channel_message_to_zerver_message). It binds to no new names: LossyConversionError, the suppress logic, and internal control flow are never referenced; 'render_block' appears only as literal message text in the fixture. Expected attachment formatting reflects base-commit render_block behavior, and the new assertion encodes the bug-fix outcome itself (rich_text messages fall back to the raw text field instead of losing content), which any correct fix produces regardless of implementation strategy."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_slack_importer.SlackImporter.test_channel_message_to_zerver_message"
  ],
  "reason": "The diff only modifies one test method: it adds a new Slack bot_message fixture entry, bumps the expected message count from 4 to 5, and adds assertions for zerver_message[4] \u2014 all inside SlackImporter.test_channel_message_to_zerver_message (the trailing context showing test_convert_slack_workspace_messages is unchanged, confirming the edits end in the preceding method)."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue clearly identifies the defect and both affected surfaces, and the expected-behavior evidence pins down a concrete, checkable input/output pair: exact Slack message JSON in and exact converted Markdown out, including the preserve-text-when-unhandled-blocks-present rule, attachment appending, non-duplication of section content, and buttons rendering to nothing."
}
