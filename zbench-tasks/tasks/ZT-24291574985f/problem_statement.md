# Fix mixed-language and inconsistent channel-creation notifications

## Background

When a new channel (stream) is created in Zulip, the server posts an automated notification message to that channel under the topic "channel events" announcing the creation. Part of that message describes the channel's permission/privacy type (e.g. public, private).

## Current (buggy) behavior

The fragment of the notification that names the channel's privacy type is translated separately from the rest of the message, using a different locale source than the surrounding text. As a result, users can see a notification that mixes two languages. For example, with the browser's preferred language set to French but the Zulip account language set to English, creating a channel produces a message that is in English except for the privacy label, which appears as "Publique" instead of "Public". The whole notification should be rendered consistently in one language (the same language as the rest of the message).

Additionally, the wording of the privacy portion of the message should clearly and uniformly identify the channel's permission policy for every policy type.

## Required behavior

1. The channel-creation notification must be rendered in a single, consistent language — the privacy/permission label must be translated with the same locale as the rest of the notification text, never with the acting user's browser locale when that differs.
2. The notification must begin by stating the channel's permission type in bold, followed by the rest of the announcement. Example shape: `**Public** channel created by {user}. **Description:** ...`.
3. Every permission policy a channel can be created with must map to a well-defined label (see below), so no policy type produces a notification with a missing or wrong privacy description.

## Interface requirements

- When a channel is created, the notification message posted to the channel's "channel events" topic must state the channel's permission type in bold at the start of the message, using these exact labels per policy (in English; the labels are translatable and must be translated together with the rest of the message): `**Web-public**` for web-public channels; `**Public**` for public channels; `**Private, shared history**` for private channels with shared history; and `**Private, protected history**` for private channels with protected history. Example: `**Public** channel created by {user}. **Description:** ...`.
- Exactly one channel-creation notification message is posted to the "channel events" topic for each newly created channel of the above four policy types. This must hold for channels created via the subscriptions API (`POST /json/users/me/subscriptions`) regardless of which combination of `is_web_public`, `invite_only`, and `history_public_to_subscribers` flags selects the policy.
- Channels created with the Zephyr-realm-only `public_protected_history` permission policy (public channels with protected history, available only in Zephyr mirror realms) must not receive any channel-creation notification message — the "channel events" topic for such a channel must contain zero messages after creation.

## Notes for implementation

- The set of permission policies is defined by `Stream.PERMISSION_POLICIES` in the server codebase; each policy is characterized by its `is_web_public`, `invite_only`, and `history_public_to_subscribers` settings. All policies defined there must be handled: the four listed above get the bold labels shown, and `public_protected_history` gets no notification.
- The bold policy label must appear verbatim (as Markdown bold) in the stored message content for an English-language rendering; translations of the label must come from the same translation pass/locale as the rest of the notification so mixed-language output is impossible.
