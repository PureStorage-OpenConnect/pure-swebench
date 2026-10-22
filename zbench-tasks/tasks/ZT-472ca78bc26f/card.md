# ZT-472ca78bc26f -- notifications: Fix AssertionError on moving messages with bot mentions.

- lang: py   issue: #39888   tier: B
- fix: https://github.com/zulip/zulip/commit/472ca78bc26f959b73fa4e64daa7444c68be8402
- f2p: zerver.tests.test_message_edit_notifications.EditMessageSideEffectsTest.test_channel_edit_does_not_notify_anybody, zerver.tests.test_message_edit_notifications.EditMessageSideEffectsTest.test_content_edit_that_also_moves_topic_notifies, zerver.tests.test_message_edit_notifications.EditMessageSideEffectsTest.test_topic_edit_does_not_notify_anybody
- p2p: zerver.tests.test_notification_data, zerver.tests.test_event_queue

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug-fix",
  "reason": "Real bug fix with observable behavioral change: topic/channel-only edits wrongly entered the notification path (causing AssertionError with bot mentions). The hidden tests grade deterministic outcomes \u2014 that topic and channel moves enqueue no notifications, and that a content edit combined with a topic move does notify the mentioned user via the expected queues. Assertions use existing structured helpers (enqueue kwargs dict, queue-name list), not rendered snapshots or exact long strings, so they fail before the fix and pass after without pinning incidental formatting."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The new tests exercise only surface that exists at the base commit. They drive the pre-existing message-edit API (POST /json/messages/<id> with the long-standing `topic`, `stream_id`, and `content` parameters) and assert user-visible outcomes: topic-only and channel-move edits must not trigger notifications, while a content edit that mentions a user must. All test scaffolding they lean on pre-exists \u2014 `_assert_update_does_not_notify_anybody` (the diff merely widens its type annotation, proving it existed), `_login_and_send_original_stream_message`, `_get_queued_data_for_message_update`, `get_maybe_enqueue_notifications_parameters`, and `register_push_device`. The asserted enqueue parameters target `maybe_enqueue_notifications`, a pre-existing function whose signature the fix does not touch, and the queue names `missedmessage_mobile_notifications` / `missedmessage_emails` are long-standing Zulip queues. The reference fix introduces no new names at all \u2014 it only changes internal logic inside `process_message_update_event` (keying on `orig_content` presence instead of the `rendering_only` flag), and the tests never reference that mechanism, so any behaviorally correct fix at this layer would pass without guessing author-specific choices."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives a concrete reproduction and stack trace, and the expected-behavior evidence pins down the exact product contract: topic-only and channel-only moves enqueue no notifications for anyone, while a combined content-edit-plus-move still notifies a newly mentioned user with mention email/push flags set and one event each on the mobile-push and email queues. Together these define a determinate, checkable outcome."
}
