# ZT-b45341991d57 -- message_edit: Invalidate cache for propagated messages on topic edit.

- lang: py   issue: #37619   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/b45341991d573485e2c27bb6759f94ed44dad125
- f2p: zerver.tests.test_message_edit.EditMessageTest.test_edit_message_content_limit, zerver.tests.test_message_edit.EditMessageTest.test_edit_message_race_condition, zerver.tests.test_message_edit.EditMessageTest.test_remove_another_user_attachment_while_editing, zerver.tests.test_message_edit.EditMessageTest.test_remove_another_user_deleted_attachment_while_editing, zerver.tests.test_message_edit.EditMessageTest.test_save_message
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "performance bug fix",
  "reason": "Behavioral fix for a real bug (topic moves with tens of thousands of messages timing out): instead of re-fetching every propagated message to rewrite the cache, the code now bulk-updates and invalidates cache entries for lazy rebuild. Hidden tests can verify observable behavior through pre-existing interfaces \u2014 e.g. that messages fetched after a propagated topic edit reflect the new topic (cache correctly invalidated, not stale), that the update event's message_ids covers all changed messages, and reduced query/cache work. Not a refactor, revert, docs, i18n, type-only, dependency, or test-only change, and nothing is time/version-gated."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "The hidden test only uses interfaces that exist at the base commit: `messages_for_ids`, `queries_captured`, `MessageEditHistoryVisibilityPolicyEnum`, and `TOPIC_NAME` are all pre-existing imports already used by the original test. It references none of the symbols the fix introduces (`cache_delete_many`, `to_dict_cache_key_id`, the changed `propagate` signature) and asserts no invented strings. It checks observable behavior \u2014 that after a message edit, a fetch populates the cache such that a subsequent fetch issues only one query that doesn't touch the message table \u2014 which is exactly the lazy-rebuild semantics of the fix expressed through existing query-counting infrastructure. A solver is free to implement the cache invalidation with any names or mechanism they choose."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_message_edit.EditMessageTest.test_save_message",
    "zerver.tests.test_message_edit.EditMessageTest.test_edit_message_content_limit",
    "zerver.tests.test_message_edit.EditMessageTest.test_remove_another_user_attachment_while_editing",
    "zerver.tests.test_message_edit.EditMessageTest.test_remove_another_user_deleted_attachment_while_editing",
    "zerver.tests.test_message_edit.EditMessageTest.test_edit_message_race_condition"
  ],
  "reason": "The diff does not touch a test_* method directly \u2014 it modifies the shared helper EditMessageTest.check_message in zerver/tests/test_message_edit.py (the hunk's docstring and queries_captured block live inside that helper; the diff hunk header only shows the enclosing class). Since check_message is not itself runnable as a tools/test-backend target, the affected targets are the test methods that call it. Grepping the file for self.check_message( call sites and mapping them to their enclosing test methods yields the five tests listed: test_save_message (line 211 call), test_edit_message_content_limit (line 1369), test_remove_another_user_attachment_while_editing (lines 2485/2497), test_remove_another_user_deleted_attachment_while_editing (lines 2529/2539), and test_edit_message_race_condition (lines 2586/2599). test_save_message is the primary/most direct exercise of the changed cache-rebuild assertions. Alternatively, the whole class target zerver.tests.test_message_edit.EditMessageTest covers everything."
}
