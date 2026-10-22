## Support Slack integration bot messages in the Slack webhook integration

### Observed behavior

Zulip's Slack webhook integration currently cannot handle messages that originate from Slack's integration bots. These bot messages arrive with a payload format that differs from ordinary Slack user messages, and they typically make heavy use of Slack's `blocks` and `attachments` message features. Because the webhook integration does not process this payload shape, such messages are not converted into Zulip messages.

### Expected behavior

When the Slack webhook integration receives a message from a Slack integration bot, it should recognize the bot-message payload format and convert the message content — including content carried in the `blocks` and `attachments` fields — into an appropriate Zulip message.

### Implementation note

The codebase already contains a helper, `process_slack_block_and_attachment`, that handles converting Slack `blocks` and `attachments` content (it is used by the Slack data import pipeline). The Slack webhook integration **must reuse this helper** to extract the message text from integration bot payloads: call `process_slack_block_and_attachment(event_dict)` to obtain the raw text, then render it with the integration's existing `convert_to_zulip_markdown`, rather than reimplementing that logic.

### Output format

The emitted Zulip message must match the output of `process_slack_block_and_attachment` followed by `convert_to_zulip_markdown`. In particular, Slack link syntax is preserved in that raw form: a link renders as the literal `<https://url|label>` (optionally wrapped in emphasis, e.g. `**<https://url|label>**`). Do NOT convert Slack links to Markdown `[label](url)`.
