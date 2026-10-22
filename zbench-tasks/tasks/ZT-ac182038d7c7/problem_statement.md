# Improve formatting of moderation request messages

## Background

Zulip has a message-reporting feature: when a realm has a moderation request channel configured, a user can report a message, and a bot posts a moderation request message to that channel describing the report. The moderation request message is composed server-side (see the message-report code paths in `zerver/`, e.g. the logic invoked by the message-report endpoint and its helpers).

## Current behavior

Today the moderation request message is built roughly like this:

- **Channel message reports** open with a header of the form `{reporting_user} reported {channel_message_link} sent by {reported_user}.`, where `{channel_message_link}` is the channel/topic/message link syntax for the reported message.
- **Direct message reports** open with `{reporting_user} reported a DM sent by {reported_user}.` (group DMs additionally append `to {recipients}`).
- The reason and notes follow as a bulleted list:

  ```
  - Reason: **{report_type}**
  - Notes:
  ```quote
  {description}
  ```
  ```

- The reported message content is then embedded in a spoiler block whose header is `**Message sent by {reported_user}**`.

This layout has problems: the reported user's pill appears twice (once in the header, once in the spoiler header), the first line wraps awkwardly because it contains the full message link, and the "Notes:" label floats above the quote block.

## Required behavior

Restructure the generated moderation request message as follows. All user references continue to use silent mention syntax (`@_**Name|id**`).

1. **Header line** (first line of the message):
   - Reported channel message: `{reporting_user} reported a message sent by {reported_user}.` — the message link is removed from the header entirely.
   - Reported 1:1 direct message: `{reporting_user} reported a direct message sent by {reported_user}.` — note the wording "direct message", not "DM".
   - Reported group direct message: `{reporting_user} reported a direct message sent by {reported_user} to {recipients}.`, where `{recipients}` is the list of silent mentions of all members of the group DM, sorted alphabetically, comma-separated, with `, and ` before the final member (e.g. `@_**Iago|11**, @_**King Hamlet|10**, and @_**Othello|12**`). Note the alphabetical ordering: previously the reporting user was listed first; now all members are sorted alphabetically regardless of role.

2. **Reason and notes**, immediately after the header, merged into a single quote block (no `- Reason:` / `- Notes:` bullets):

   ````
   ```quote
   **{report_type}**. {description}
   ```
   ````

   That is: the report type in bold, then a literal period and space, then the reporter's description, all on one logical line inside the quote block.

3. **Reported message content**, after the quote block and separated from it by a blank line, inside a spoiler fence. As today, the fence characters must be chosen via the existing unused-fence helper (`get_unused_fence`) applied to the reported message content, so the fence never collides with fences inside the quoted message. The spoiler header changes:
   - Channel message: `{fence} spoiler **Original message at {channel_message_link}**`, where `{channel_message_link}` is produced by the existing `get_message_link_syntax` helper (channel/topic/message link syntax, `#**channel>topic@message_id**`-style) for the reported message. If the channel/topic name would produce broken link syntax, existing fallback handling for that case should continue to apply.
   - Direct message (both 1:1 and group): `{fence} spoiler **[Original message]({url})**`, where `{url}` is the near-message narrow URL to that DM conversation for the reported message id, produced by the existing `pm_message_url` helper (the standard DM permalink built from the realm, the reported message id, and the DM recipients).

### Full resulting shapes

Channel message report:

````
{reporting_user} reported a message sent by {reported_user}.
```quote
**{report_type}**. {description}
```

{fence} spoiler **Original message at {channel_message_link}**
{reported_message_content}
{fence}
````

Direct message report (1:1 shown; group DM differs only in the header's `to {recipients}` suffix):

````
{reporting_user} reported a direct message sent by {reported_user}.
```quote
**{report_type}**. {description}
```

{fence} spoiler **[Original message]({direct_message_link})**
{reported_message_content}
{fence}
````

Existing behavior that must be preserved: silent mentions for all users, truncation handling of long reported content, and delivery of the report to the configured moderation request channel.

## Interface requirements

- The report header for a reported channel message must read `{reporting_user} reported a message sent by {reported_user}.` using silent mention syntax for both users, with no message link in the header.
- The report header for a reported 1:1 direct message must read `{reporting_user} reported a direct message sent by {reported_user}.` ("direct message" replaces the old "DM" wording).
- The report header for a reported group direct message must read `{reporting_user} reported a direct message sent by {reported_user} to {recipients}.` where `{recipients}` lists silent mentions of all group members sorted alphabetically, comma-separated, with `, and ` before the final member.
- Immediately after the header, the report reason and notes must appear as a single Markdown quote block whose content is `**{report_type}**. {description}` (bold report type, a period and space, then the reporter's description), replacing the old `- Reason:`/`- Notes:` bullet format.
- After the quote block (separated by a blank line), the reported message content must appear inside a spoiler fence built with an unused fence for the quoted content.
- For a reported channel message, the spoiler header must be `**Original message at {channel_message_link}**` where `{channel_message_link}` is the existing channel/topic/message link syntax (`get_message_link_syntax`) for the reported message.
- For a reported direct message (1:1 or group), the spoiler header must be `**[Original message]({url})**` where `{url}` is the near-message narrow URL to that direct-message conversation produced by the existing `pm_message_url` helper (i.e. the standard DM permalink for the reported message id and its recipients).
