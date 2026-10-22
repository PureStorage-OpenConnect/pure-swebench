# Lossy Slack message conversion when `rich_text` blocks are mixed with supported blocks

## Context

Zulip converts Slack messages to Zulip messages in two places that share the same conversion helper:

- the Slack data importer (`zerver/data_import/slack.py` and its helpers), and
- the Slack incoming webhook integration.

Slack messages can carry content in three places: the plain `text` field, a top-level `blocks` array (Block Kit), and an `attachments` array (whose entries may themselves contain `blocks`). The conversion pipeline (`process_slack_block_and_attachment` and the block/attachment rendering helpers it calls) knows how to render some block types (e.g. `section`, `context`, `divider`, image-style elements) into Zulip Markdown, and treats others as unhandled. `rich_text` — the block type Slack uses for ordinary formatted user text (bold, italic, links, etc.) — is one of the unhandled types, and it is extremely common.

## The bug

When the converter finds that it can render *at least one* block or attachment from a message, it replaces the message's `text` field wholesale with the rendered output of only the blocks it understood. Any content that lived in an unhandled block type is silently dropped.

Concretely: if a message mixes a `rich_text` block (the user's actual prose) with any block type the converter supports (say, a `section` block or an attachment with blocks), the entire `rich_text` portion of the message vanishes from the converted Zulip message. For example, a Slack message that reads "here's a message and an url to preview!" followed by a link-preview attachment arrives in Zulip with only the preview content — the prose is gone.

This data loss affects both the Slack importer and the Slack incoming webhook, since both go through the same conversion code.

## Required behavior

The conversion must never discard message content because it appeared in an unhandled block type. Slack always populates the message's plain `text` field with a fallback rendering of the message body (including `rich_text` content), so that text is available to preserve.

Specifically, when converting a message:

1. If the message's top-level `blocks` contain **any** block type the converter cannot handle (notably `rich_text`), the converter must not replace the message's `text` with a partial rendering of the top-level blocks. The original `text` field content must be kept as the body of the converted message (this avoids both losing the `rich_text` content and duplicating content that appears in both `text` and a supported top-level block).
2. Content from `attachments` that the converter *can* render must still be rendered and appended after that preserved text, separated by a newline, in the same Markdown formats the converter already produces (e.g. a `section` block with mrkdwn `*<url|label>*` becomes `**[label](url)**`; a `context` block renders its image elements as `[alt_text](image_url)` and its mrkdwn/text elements as plain text, with the elements separated by blank lines).
3. Blocks with no meaningful text representation, such as `actions` blocks containing buttons, must contribute nothing to the output (and must not count as content loss).
4. If everything in the message is representable via handled blocks/attachments (the pre-existing happy path), conversion output should be unchanged from current behavior.

### Worked example

A Slack bot message with:

- `text`: `` `render_block` will delete me, help!\nHello, `render_block` recognizes me. ``
- top-level `blocks`: a `rich_text` block containing the text `` `render_block` will delete me, help! `` followed by a `section` block with plain text `` Hello, `render_block` recognizes me. ``
- one attachment whose `blocks` are: a `section` with mrkdwn `*<https://app.clickup.com/t/25567147/86cw30wf2|asd>*`; a `context` block with elements (image with alt text `Cookie / The Goodiest of Cstdddddsdd / dds`, mrkdwn `in dds`, image with alt text `Status`, mrkdwn `To Do`); and an `actions` block with two buttons

must produce exactly this Zulip message content:

```
`render_block` will delete me, help!
Hello, `render_block` recognizes me.
**[asd](https://app.clickup.com/t/25567147/86cw30wf2)**

[Cookie / The Goodiest of Cstdddddsdd / dds](https://search.clickup-au.com/media/app-icons/clickup/logo_alpha.png)

in dds

[Status](https://search.clickup-au.com/media/app-icons/clickup/status.png)

To Do
```

Note that the first two lines come from the preserved `text` field (the `rich_text` line is no longer lost, and the `section` line is not duplicated), the attachment's rendered blocks follow, and the buttons produce no output.

## Scope

- The fix must apply to both consumers of the shared conversion code: the Slack importer and the Slack incoming webhook.
- Messages processed by the importer must otherwise flow through unchanged (sender attribution, channel routing, message counts, etc. are unaffected — a message like the example above is one normal imported message).

## Interface requirements

(none)
