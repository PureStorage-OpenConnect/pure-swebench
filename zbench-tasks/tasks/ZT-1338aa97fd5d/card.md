# ZT-1338aa97fd5d -- message_send: Optimize get_recipients_for_user_creation_events.

- lang: py   issue: #27835   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/1338aa97fd5dd89fa70505999d02ace5e2ec175f
- f2p: zerver.tests.test_message_send.PersonalMessageSendTest.test_group_direct_message
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "performance-optimization",
  "reason": "Small, well-specified performance fix with observable behavior: adds an early-return in get_recipients_for_user_creation_events when all DM participants already share a DirectMessageGroup with prior messages, avoiding expensive follow-up queries. A hidden test can verify this through pre-existing interfaces (e.g., database query counts on message send, or the function's returned recipient dict) without touching migrations, versions, docs, or schema bookkeeping. None of the drop criteria apply \u2014 it is not a refactor, revert, test-only, or gated change."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "The hidden test only adjusts numeric query-count expectations in pre-existing assertions (assert_database_query_count with send_group_direct_message), all of which exist at the base commit. It references no new symbols, functions, or strings introduced by the fix \u2014 it asserts the observable behavioral outcome (fewer database queries for messages to existing direct message groups), which any valid optimization would satisfy without needing the author's exact implementation names like get_direct_message_group_hash."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_message_send.PersonalMessageSendTest.test_group_direct_message"
  ],
  "reason": "The diff only changes assert_database_query_count values inside one existing method. The hunk context (group direct message query counts, ending just before test_direct_message_initiator_group_setting) sits inside PersonalMessageSendTest.test_group_direct_message \u2014 confirmed against the Zulip source, where the 'guest with limited user access' context lines fall within that method. No new test methods are added."
}
