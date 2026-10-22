# Convert Slack bot/integration messages in the Slack import tool

## Background

Zulip's Slack data import tool (invoked via `./manage.py convert_slack_data`) converts a Slack export into Zulip's import format. Today it effectively ignores messages posted by Slack bots — in particular integration notifications (e.g. from ClickUp, GitHub, etc.). These messages have no `"user"` field; instead they look like:

```json
{
    "subtype": "bot_message",
    "text": "",
    "username": "ClickUp",
    "attachments": [ { "id": 1, "blocks": [ { "type": "section", "text": { "type": "mrkdwn", "text": "<https://app.clickup.com/t/86cuwzrde| dddssd>", "verbatim": false } }, ... ], "color": "#656f7d", "fallback": "[no preview available]" } ],
    "type": "message",
    "ts": "1710748557.084959",
    "bot_id": "B06NWMNUQ3W",
    "app_id": "A3G4A68V9"
}
```

whereas an ordinary user message carries `"user": "U06NU4E26M9"` and its content in `"text"`/rich-text `"blocks"`. Bot messages typically have an empty `"text"` and carry their real content inside `"attachments"` (either legacy attachment fields like `title`/`title_link`/`text`, or Block Kit `blocks`).

Separately, Zulip already knows how to render Slack attachments and Block Kit blocks to Zulip Markdown: the Slack-compatible incoming webhook (`zerver/webhooks/slack_incoming/view.py`) contains this rendering logic (functions along the lines of `render_attachment` and `render_block`).

## Required changes

### 1. Extract the sender for bot messages

In `zerver/data_import/slack.py`, the helper `get_message_sending_user` currently only reads the `"user"` field, so bot messages have no identifiable sender. It must be updated (along with its callers) so that for a bot message the sender is taken from `"bot_id"`. Messages that have neither a user nor a bot sender should continue to be skipped as before.

### 2. Fetch bot user data for shared/imported channels

In `fetch_shared_channel_users` (same module), once bot IDs can be extracted from messages, bot senders that are not in the export's user list must be fetched from Slack and added to the user list so mirror users can be created for them. Fetching data for a bot ID must use Slack's `bots.info` API (`https://slack.com/api/bots.info`, parameter `bot=<bot_id>`) rather than the `users.info` API used for regular users. The fetched bot must be added to the user list with its Slack `bot_id` (e.g. `B06NWMNUQ3W`) as its ID so that the existing Slack-user-ID → Zulip-user-ID mapping works for bots too.

### 3. Share the attachment/block rendering code

Move the attachment and block rendering logic (`render_attachment`, `render_block`, and whatever helpers they need) out of `zerver/webhooks/slack_incoming/view.py` into `zerver/data_import/slack_message_conversion.py`. The incoming webhook must be updated to import and use the shared code from its new location so behavior there is unchanged; remove the now-duplicated code from the webhook module.

### 4. Convert bot message content during import

During message conversion (`channel_message_to_zerver_message` and its helpers), a message with `"subtype": "bot_message"` must:

- be imported as a real message (not dropped), with its Zulip sender being the Zulip user ID mapped from the message's `bot_id`;
- have its content produced by rendering its `attachments` (using the shared rendering logic above), since the top-level `text` is typically empty. Multiple attachments/blocks are joined with blank lines, and the final content is stripped of leading/trailing whitespace.

The rendering must behave as it does for the Slack-compatible incoming webhook. Concretely, these are the required outcomes:

**Legacy attachment (title + title_link + mrkdwn text).** Given an attachment:

```json
{
  "id": 1,
  "color": "008844",
  "fallback": "dsdaddsa",
  "text": "Added assignee Pieter\n\nby Pieter\n_<https://app.clickup.com/25567147/v/s/43687023|Task one> &gt; <https://app.clickup.com/25567147/v/li/901601846060|dsad>_",
  "title": "dsdaddsa",
  "title_link": "https://app.clickup.com/t/86cv0v5my",
  "mrkdwn_in": ["text"]
}
```

the resulting Zulip message content must be exactly:

```
## [dsdaddsa](https://app.clickup.com/t/86cv0v5my)

Added assignee Pieter

by Pieter
*[Task one](https://app.clickup.com/25567147/v/s/43687023) &gt; [dsad](https://app.clickup.com/25567147/v/li/901601846060)*
```

That is: the title becomes a `##` heading linking to `title_link`; Slack mrkdwn links `<url|label>` become Markdown `[label](url)`; `_..._` italics become `*...*`; already-escaped entities like `&gt;` are left as-is.

**Block Kit attachment.** Given an attachment whose content is in `blocks`:

```json
{
  "id": 1,
  "blocks": [
    {"type": "section", "block_id": "qvtCh", "text": {"type": "mrkdwn", "text": "<https://app.clickup.com/t/86cv0v5my| dsda>", "verbatim": false}},
    {"type": "section", "block_id": "7LtRa", "text": {"type": "mrkdwn", "text": "Task Created\nBy Pieter\n", "verbatim": false}},
    {"type": "section", "block_id": "XgOBF", "fields": [{"type": "mrkdwn", "text": "_<https://app.clickup.com/25567147/v/s/43687023|Task one> &gt; <https://app.clickup.com/25567147/v/li/901601846060|dsad>_", "verbatim": false}]}
  ],
  "color": "#656f7d",
  "fallback": "[no preview available]"
}
```

the resulting content must be exactly:

```
[ dsda](https://app.clickup.com/t/86cv0v5my)

Task Created
By Pieter

*[Task one](https://app.clickup.com/25567147/v/s/43687023) &gt; [dsad](https://app.clickup.com/25567147/v/li/901601846060)*
```

(Each section block is rendered — text sections as converted mrkdwn, field sections as their converted field texts — and blocks are separated by blank lines.)

**Attachment with a link in the title and plain mrkdwn text** must likewise render as a heading plus body, e.g. producing:

```
## [Buy Ingredients!](https://app.clickup.com/t/86cuy8e4y?comment=90160026391938)

New comment:  where can I buy it?

by Pieter
*[Task one](https://app.clickup.com/25567147/v/s/43687023) &gt; [dsad](https://app.clickup.com/25567147/v/li/901601846060)*
```

### Additional expectations

- If a bot user (keyed by its `bot_id`) is present in the import's user data and Slack-ID→Zulip-ID mapping, its imported messages' `sender` must resolve through that mapping exactly like a regular user's.
- Bot messages rendered this way should not create Zulip `Attachment`/upload records — the Slack "attachments" here are formatted content, not files.
- Existing behavior for regular user messages, filtered subtypes (e.g. `channel_join`), threads, and the incoming webhook's rendering must be unchanged.
- The end-to-end path is `./manage.py convert_slack_data`; the conversion must work within that flow (including the Slack API token handling already used for user fetching).
