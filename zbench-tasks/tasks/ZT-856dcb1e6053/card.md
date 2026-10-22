# ZT-856dcb1e6053 -- reminder: Generate accurate `with` topic link.

- lang: py   issue: #38089   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/856dcb1e6053c3184b62a49463fcf278ea20d95d
- f2p: zerver.tests.test_reminders.RemindersTest.test_notes_in_reminder, zerver.tests.test_reminders.RemindersTest.test_schedule_reminder, zerver.tests.test_reminders.RemindersTest.test_successful_deliver_channel_message_reminder
- p2p: zerver.tests.test_topic_link_util

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavioral bug fix",
  "reason": "Fixes a user-visible bug where reminders for channel messages produced an inaccurate topic link. The change alters observable output \u2014 the formatted reminder content now includes a properly escaped display link wrapping a message URL, and StreamTopicPattern markdown rendering uses the shared display syntax. This is testable through pre-existing interfaces (reminder content generation and markdown rendering), involves no refactor-only/docs/i18n/version-gated concerns, and the small diffstat (4 files, +32/-11) fits a well-scoped fix."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "The hidden test imports no new symbols and calls only pre-existing APIs (schedule_reminder endpoints, ScheduledMessage.content). It asserts the user-visible reminder message content \u2014 that the '#channel > topic' reference is rendered as a markdown link to the specific message. The asserted string is built from conventions that already exist at the base commit: the '#Verona > test' display format matches the existing rendered stream-topic link text in zerver/lib/markdown (the linked branch already emits '#{stream_name} > {topic}'), and the '/with/{msg_id}' URL comes from the pre-existing stream_message_url(..., conversation_link=True) helper (imported, not added, by the fix). The new constant TOPIC_LINK_SYNTAX_FOR_DISPLAY introduced by the fix is never referenced by the test. A solver implementing the described behavior with any internal naming would pass; the test couples only to observable output, not to the author's chosen symbols."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_reminders.RemindersTest.test_schedule_reminder",
    "zerver.tests.test_reminders.RemindersTest.test_successful_deliver_channel_message_reminder",
    "zerver.tests.test_reminders.RemindersTest.test_notes_in_reminder"
  ],
  "reason": "The second and third hunks are both inside test_notes_in_reminder (confirmed against the file: that method contains the 'Note:' assertion for a channel message and the '{123}'/'{789}' formatting-characters assertion, and it immediately precedes test_schedule_reminder_ones_own_message). The first hunk modifies the helper get_channel_message_reminder_content, which is not itself a test but defines the expected content asserted in test_schedule_reminder and test_successful_deliver_channel_message_reminder, so those two tests' behavior is modified by the diff as well."
}
