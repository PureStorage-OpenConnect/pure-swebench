# Create `UserMessage` rows for outgoing webhook and embedded bots, and track message processing via the `read` flag

## Background

Zulip supports "service bots": outgoing webhook bots (`UserProfile.OUTGOING_WEBHOOK_BOT`) and embedded bots (`UserProfile.EMBEDDED_BOT`). When a message is sent, the message-send code path decides which users get a `UserMessage` row (the per-user record that drives message access, flags such as `read`/`mentioned`, unread counts, narrows, etc.).

## Current behavior

As a performance optimization, service bots are deliberately excluded from `UserMessage` creation: `get_recipient_info` in the message-send path filters service bots out of the set of users that receive `UserMessage` rows. Instead, `get_service_bot_events` computes which messages should trigger each service bot (via the trigger conditions: direct message to the bot, or a mention of the bot), and events are enqueued for the appropriate queue worker (`OutgoingWebhookWorker` or `EmbeddedBotWorker`).

This causes a real bug: outgoing webhook bots fail `has_message_access` checks for messages they legitimately should be able to access (for example, messages sent directly to them), because access checks rely on the existence of a `UserMessage` row. This contradicts the documented promise that outgoing webhook bots have the same rights and permissions as a generic bot.

## Required behavior

1. **Service bots must get `UserMessage` rows like any other user.** Stop filtering outgoing webhook and embedded bots out in `get_recipient_info`. For any message where a generic bot user would receive a `UserMessage` row (direct message recipient, subscribed to the channel, mentioned, etc.), an outgoing webhook bot or embedded bot in the same position must also receive one, with the normal flags (`mentioned`, etc.) computed the same way as for other users. As a result, `has_message_access` and everything else driven by `UserMessage` rows works for service bots without special-casing.

2. **The `read` flag must record whether the service bot's queue processor has handled the message.**
   - Compute the service-bot event plan (`get_service_bot_events`) *before* creating `UserMessage` rows, so its conclusions are available when rows are created.
   - When creating a service bot's `UserMessage` row: if the message is going to be dispatched to that bot for processing (i.e., it appears in that bot's planned service-bot events), the row must be created **without** the `read` flag set. If the message will *not* be dispatched to the bot, create the row with `read` set (as is done for messages a user doesn't need to act on), so it doesn't linger as spurious unread state.
   - When the relevant queue worker consumes the event — `OutgoingWebhookWorker` for outgoing webhook bots and `EmbeddedBotWorker` for embedded bots — it must mark the corresponding message(s) as `read` for that bot user, so the flag reflects that the bot has processed the message. This behavior must be identical across both service bot types.

3. **No change to which events are triggered.** The set of messages that cause an outgoing webhook call or embedded bot invocation (direct messages to the bot, mentions of the bot) must remain exactly as today; this change only adds `UserMessage` bookkeeping around it. A service bot must still not trigger on its own messages.

## Notes and constraints

- The observable end state after a message is sent and the worker has processed it: the service bot has a `UserMessage` row for the message, flagged `read`.
- For a message the bot receives but is not notified about (e.g., an un-mentioned channel message on a channel the bot is subscribed to), the bot still gets a `UserMessage` row, already marked `read`.
- Both bot types (outgoing webhook and embedded) must behave identically with respect to `UserMessage` creation and the processed/`read` flag lifecycle; don't implement this for only one worker.
- Be careful about ordering within the send-message transaction: the decision about the initial `read` flag depends on the planned service-bot events, so that computation has to happen before `UserMessage` rows are persisted.
- Consider existing service bots: think about whether any related code assumed service bots never have `UserMessage` rows (e.g., unread-count queries, soft-deactivation logic) and keep those paths correct.

## Interface requirements

None beyond the existing names referenced above (`get_recipient_info`, `get_service_bot_events`, `OutgoingWebhookWorker`, `EmbeddedBotWorker`), whose roles must be preserved as described.
