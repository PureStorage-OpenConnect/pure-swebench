# Show a dedicated empty-feed notice when a channel's messages are all in muted topics

## Context

In the Zulip web app, when a user narrows to a single channel (e.g. via the left sidebar), an "empty narrow" banner is shown if the message feed has nothing to display. Today, for a channel the user is subscribed to, that banner always says:

> **There are no messages here.**
> Why not [start the conversation]?

(The second line contains the `start the conversation` compose link.)

This banner is misleading in one specific situation: the channel actually *does* contain messages, but every one of them is in a topic the user has muted. Because muted-topic messages are filtered out of the channel feed, the feed renders as empty and the user is told there are "no messages here" and invited to start a conversation — even though conversations already exist.

## Required behavior

When the user narrows to a channel they are subscribed to and the rendered feed is empty, the empty-narrow banner must distinguish two cases:

1. **The feed is empty only because of muted topics** — the channel contains messages, but none are visible because all of its topics are muted. In this case, show a dedicated notice (formatted like the other empty-narrow banners, with a title line and a secondary HTML line) instead of the "start the conversation" prompt:
   - Title (translatable user-facing string, exact text): `You have muted all the topics in this channel.`
   - Body (translatable user-facing HTML, exact content): `To view a muted topic, click <b>show all topics</b> in the left sidebar, and select one from the list. Learn more` — where "Learn more" is a hyperlink to `/help/mute-a-topic` that opens in a new tab (`target="_blank" rel="noopener noreferrer"`).
   - The "Why not start the conversation?" line must not appear in this case.

2. **The channel genuinely has no messages at all** (muted or otherwise). In this case, keep the existing default banner exactly as it is today: "There are no messages here." with the "Why not start the conversation?" compose link.

All other empty-narrow cases (e.g. narrowing to a channel that does not exist, unsubscribed channels, non-channel narrows) must keep their current banners unchanged.

## Distinguishing the two cases

The current message list object already exposes what is needed to tell these apart, and the implementation should use it rather than inventing new state:

- `visibly_empty()` on the current message list reports whether the rendered feed has no visible messages.
- `empty()` on the current message list reports whether the underlying list has no messages at all (including ones hidden by topic muting).

So the muted-topics notice applies when the feed is visibly empty but the list is not truly empty (`visibly_empty()` is true and `empty()` is false); the default "no messages here" banner applies when the list is truly empty (`empty()` is true).

## Interface requirements

- When the user narrows to a channel they are subscribed to and the message feed renders as empty even though the channel contains messages (i.e. every message is in a muted topic — determinable via the current message list's pre-existing `visibly_empty()` and `empty()` methods), the empty-narrow banner must show a muted-topics notice instead of the "start the conversation" prompt.
- The muted-topics banner title is the user-facing string: `You have muted all the topics in this channel.`
- The muted-topics banner body is the user-facing HTML: `To view a muted topic, click <b>show all topics</b> in the left sidebar, and select one from the list. Learn more` — where "Learn more" is a link to `/help/mute-a-topic` opening in a new tab (`target="_blank" rel="noopener noreferrer"`).
- When the channel genuinely has no messages at all (the current message list is truly empty), the existing "Why not start the conversation?" banner must still be shown, unchanged.

## Notes

- Both new strings must go through the app's usual translation/internationalization mechanisms, like the existing empty-narrow banner strings.
- The relevant banner logic lives in the web client's empty-narrow banner code (the module responsible for choosing which empty-feed message to show for a given narrow filter).
