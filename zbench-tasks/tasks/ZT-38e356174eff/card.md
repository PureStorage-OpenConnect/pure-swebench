# ZT-38e356174eff -- message_send: Optimize computing inaccessible users.

- lang: py   issue: #27835   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/38e356174eff332e80bcfe672f71849a82447d16
- f2p: zerver.tests.test_message_send.PersonalMessageSendTest.test_group_direct_message, zerver.tests.test_message_send.PersonalMessageSendTest.test_personal_message
- p2p: zerver.tests.test_users

## screen: suitability
{
  "verdict": "keep",
  "task_type": "performance-optimization",
  "reason": "Small, well-specified performance improvement to the message-send path with an accompanying observable behavior change: the new get_inaccessible_users_queryset drops the is_user_active=True filter and uses an Exists() subquery, and check_sender_can_access_recipients now short-circuits with has_inaccessible_users (including a self-DM fast path and existence check instead of materializing IDs). Hidden tests can exercise this through pre-existing interfaces \u2014 sending DMs as a limited guest to accessible/inaccessible/deactivated recipients and asserting the permission error or success, plus standard database query-count assertions on the send-message endpoint. It is not a pure refactor, revert, docs, i18n, type-only, dependency, or test-only change, and nothing here is time/version-gated or tied to API feature-level bookkeeping."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "The hidden test only modifies expected values in pre-existing assert_database_query_count() assertions and updates surrounding comments; it uses only pre-existing test helpers (send_personal_message, send_group_direct_message, assert_database_query_count). It never imports or references the new symbols the fix introduces (has_inaccessible_users, get_inaccessible_users_queryset), asserts no new error strings, and checks a user-visible/measurable outcome (reduced DB query counts) that any equivalent optimization would satisfy. The exact counts are strict, but they constrain the performance behavior, not the author's chosen symbol names or implementation structure."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_message_send.PersonalMessageSendTest.test_personal_message",
    "zerver.tests.test_message_send.PersonalMessageSendTest.test_group_direct_message"
  ],
  "reason": "The diff only changes assert_database_query_count values inside two existing methods of PersonalMessageSendTest in zerver/tests/test_message_send.py. The first hunk's header shows only the class, so I confirmed against the upstream source that the polonius/hamlet/prospero query-count assertions are in test_personal_message; the second hunk (send_group_direct_message counts) is in test_group_direct_message, whose def appears as context at the end of the first hunk. test_direct_message_initiator_group_setting appears only as trailing context and is unmodified."
}
