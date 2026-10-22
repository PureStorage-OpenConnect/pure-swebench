# Moving a message must not trigger mention notifications (crashes the push-notification worker for bot mentions)

## Context

Zulip lets users edit a message's topic or move it to another channel, with or without also editing its content. Separately, when a message mentions a user, that user can receive push and email notifications, which are enqueued onto the `missedmessage_mobile_notifications` and `missedmessage_emails` queues and processed by workers. The push-notification path is only valid for human users: `handle_push_notification` in `zerver/lib/push_notifications.py` asserts `not user_profile.is_bot`.

## Current (buggy) behavior

When a message that contains a mention is *moved* (its topic is changed, or it is moved to a different channel) without any content change, the message-edit pipeline re-processes the mentions and enqueues mention notifications again. Two problems follow:

1. **Worker crash on bot mentions.** If the mentioned account is a bot, a push-notification event is enqueued for the bot, and the `missedmessage_mobile_notifications` worker crashes:

```
ERR  [] Problem handling data on queue missedmessage_mobile_notifications
Traceback (most recent call last):
  ...
  File "/srv/zulip/zerver/lib/push_notifications.py", line 1697, in handle_push_notification
    assert not user_profile.is_bot
AssertionError
```

Reproduction: send a channel message @-mentioning any bot, then move that message to another topic.

2. **Spurious re-notification of humans.** The same mechanism means a human who was already mentioned in a message can be notified again merely because someone moved the message, even though nothing about the content changed.

## Required behavior

A pure move edit must be notification-silent, while a content edit that happens to be combined with a move must still notify normally. Concretely:

1. **Topic-only edit notifies nobody.** When an edit request changes only the message's topic (content unchanged), no notification work of any kind may result for any user — no events on the push-notification or email-notification queues, no push notifications sent, no missed-message emails. This must hold even when the message body contains mentions (of humans or bots) and the mentioned users have push devices registered and notifications enabled.

2. **Channel-move-only edit notifies nobody.** The same guarantee applies when an edit request changes only the destination channel (`stream_id`), moving the message to another channel: no notifications for anybody, regardless of mentions in the message.

3. **Bots are never enqueued for push notifications.** As a consequence of (1) and (2), moving a message that mentions a bot must complete without ever placing a push-notification event for the bot on the queue, so the worker's `assert not user_profile.is_bot` is never hit and the move produces no worker errors.

4. **Content edits still notify, even when combined with a move.** When a single edit request both changes the message content (e.g. adds a mention of a user who was not previously mentioned) and moves the message to a new topic, the newly mentioned user must be notified exactly as they would be for a plain content edit:
   - The notification decision for the mentioned user must reflect a personal mention: mention-triggered email notification and mention-triggered push notification both apply, the message ID is the edited message's ID, the acting user is the editor, and no prior notification for this message is recorded as already delivered.
   - Exactly two queue events result from the edit: one on `missedmessage_mobile_notifications` and one on `missedmessage_emails` (the push event enqueued before the email event).

The fix must be at the point where the message-edit pipeline decides whom to notify (i.e., stop enqueuing notifications for move-only edits), not by suppressing or swallowing the error in the notification workers — mentioned-user notification data should simply not be generated or acted on when the edit contains no content change.

## Notes for verification

- "Move" covers both topic changes and channel changes, alone or together, as long as content is untouched.
- The guarantee is "notifies nobody", not just "doesn't notify bots": a topic move of a message mentioning a human with a registered push device must produce zero push and zero email notifications for that human.
- Existing behavior for plain content edits (adding a mention notifies the newly mentioned user) must be preserved.
