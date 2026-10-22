# Add the reported message's send time to moderation-report notices

## Background

Zulip has a message-reporting (moderation) feature: when a user reports a message, a notification bot posts a notice into a moderation topic that moderators follow. The first line of that notice is a header sentence identifying who reported the message and who sent it, followed by a quoted snippet of the reported message and the report details.

Currently the header line does not say *when* the reported message was sent. For example, for a reported channel message the header reads:

```
{reporting_user_mention} reported a message sent by {reported_user_mention}.
```

Moderators reviewing reports need the original message's timestamp to be visible directly in the notice.

## Required behavior

Append the reported message's send time to the end of the header sentence, in every variant of the report notice. The timestamp must be the reported message's `date_sent`, rendered using Zulip's *global time* markdown syntax (the `<time:...>` syntax that clients render in each viewer's local timezone), so that each moderator sees the time localized for them.

The user mentions in these headers are silent mentions, exactly as today; only the ` at {time}` suffix (inserted before the final period) is new. The four header variants must read exactly:

1. **Reported channel message:**
   `{reporting_user_mention} reported a message sent by {reported_user_mention} at {time}.`
2. **Reported 1:1 direct message, where the reporter is not the sender:**
   `{reporting_user_mention} reported a direct message sent by {reported_user_mention} at {time}.`
3. **User reporting their own direct message (sender and reporter are the same user):**
   `{reporting_user_mention} reported a direct message sent by {reported_user_mention} to {recipient_mention} at {time}.`
4. **Reported group direct message:**
   `{reporting_user_mention} reported a direct message sent by {reported_user_mention} to {recipient_users} and {last_recipient_user} at {time}.`
   The recipient-list formatting (sorted mentions, comma separation, including the Oxford comma when there are more than two listed recipients before the final one) is unchanged from the existing behavior; only the ` at {time}` suffix is added before the period.

In all cases `{time}` is the reported message's `date_sent` rendered in global-time markdown syntax. This applies regardless of how the direct message conversation is stored (personal recipients or direct message groups).

Everything else about the notice — the quoted message snippet, report type/description lines, message links, the topic the notice is posted to, and truncation behavior — is unchanged.

## Interface requirements

- A public helper function `datetime_to_global_time(date_sent)` must exist in the module `zerver.lib.timestamp`. It takes a datetime and returns the string rendering of that timestamp in Zulip's global-time markdown syntax (e.g. `<time:...>`), so that any code embedding message timestamps in message content can reuse it. The report-notice code must use this helper to render the timestamp.
- The moderation-report header for a reported channel message must read exactly: `{reporting_user_mention} reported a message sent by {reported_user_mention} at {time}.`, where `{time}` is the reported message's `date_sent` rendered via `datetime_to_global_time`.
- The header for a reported 1:1 direct message (reporter is not the sender) must read exactly: `{reporting_user_mention} reported a direct message sent by {reported_user_mention} at {time}.`
- The header when a user reports their own direct message must read exactly: `{reporting_user_mention} reported a direct message sent by {reported_user_mention} to {recipient_mention} at {time}.`
- The header for a reported group direct message must read exactly: `{reporting_user_mention} reported a direct message sent by {reported_user_mention} to {recipient_users} and {last_recipient_user} at {time}.` (recipient list formatting unchanged from existing behavior, with the ` at {time}` suffix appended before the period).
