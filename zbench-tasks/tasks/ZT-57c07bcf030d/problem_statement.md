# Slack webhook integration: show Slack display names instead of email-derived names

## Context

Zulip ships an incoming webhook integration for Slack (`zerver/webhooks/slack/`). When a Slack message is forwarded to Zulip via this integration, the integration resolves Slack user IDs to human-readable names by calling the Slack API (`users.info`). Resolved names are used in two places:

1. **Sender attribution**: each forwarded message is prefixed with the sender's name in bold, e.g. `**<name>**: <message text>`.
2. **Inline user mentions**: Slack mentions of the form `<@U123ABC>` inside the message body are translated to Zulip-style silent mention text, e.g. `@**<name>**`.

## Current (incorrect) behavior

The integration currently resolves a Slack user to the local part of their email address (the portion before `@domain`). For example, if the Slack user "John Doe" has the email `john.doe.private@example.com`, a message they send arrives in Zulip as:

> **john.doe.private**: Hello from Slack to Zulip.

and a mention of that user in a message body renders as `@**john.doe.private**`.

This has two problems:

- It leaks the user's (possibly private) email address into Zulip message content instead of showing their chosen display name.
- It forces Slack app administrators to grant the `users:read.email` Bot Token Scope to the Slack app, since the integration depends on reading users' email addresses.

## Required behavior

Resolve Slack users to their Slack display name (the human-readable name from the Slack user profile, e.g. "John Doe") rather than anything derived from their email address. Concretely:

- A message from the user above must arrive in Zulip as:

  > **John Doe**: Hello from Slack to Zulip.

- Inline mentions in the message body must render using the same display name, e.g. a message mentioning that user three times must produce `@**John Doe** @**John Doe** @**John Doe** hello, this is a message with mentions`.
- This applies uniformly wherever the integration renders a resolved user name, including messages that combine user mentions with channel references (e.g. `@**John Doe** **#general** message with both channel and user mentions`) and mentions nested inside other formatting.
- The email address must not appear anywhere in the forwarded message content.
- After this change, the integration must work without the `users:read.email` Bot Token Scope on the Slack app — i.e. it must not depend on the email field of Slack API user responses. Update the integration's setup documentation (`zerver/webhooks/slack/doc.md` or equivalent) if it instructs users to grant that scope.

## Notes for implementation

- The Slack `users.info` API response contains several name fields (`name`, `real_name`, `profile.display_name`, `profile.real_name`). Pick the field that corresponds to the human-readable name shown in Slack (for a user whose profile says "John Doe", the resolved name must be exactly `John Doe`).
- The existing message formatting conventions (bold sender prefix `**{name}**: `, mention syntax `@**{name}**`, channel syntax `**#{channel}**`, and the topic naming scheme) must be preserved; only the source of the user name changes.
- Behavior for messages without mentions, channel mentions, special mentions (e.g. `@all`), and token validation (including the existing invalid-token error message) must remain unchanged.
