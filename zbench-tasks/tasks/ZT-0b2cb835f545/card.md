# ZT-0b2cb835f545 -- topics: Apply automatic follow/unmute when message moved to new topic.

- lang: py   issue: #28408   tier: B
- fix: https://github.com/zulip/zulip/commit/0b2cb835f545f52a49966c3da1d287fbf820491c
- f2p: zerver.tests.test_message_edit.EditMessageTest.test_automatic_follow_policy_in_channel_with_protected_history, zerver.tests.test_message_edit.EditMessageTest.test_move_message_to_new_topic_with_automatic_follow_policy, zerver.tests.test_message_edit.EditMessageTest.test_move_message_to_new_topic_with_automatic_unmute_policy
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, high-priority feature from a tracked issue: applying the automatic follow/unmute topic-visibility policy when a message is moved to a new topic. The hidden test exercises observable behavior end-to-end \u2014 it moves messages via the API and asserts on which user IDs end up with FOLLOWED/UNMUTED visibility policy, including edge cases (preexisting messages in target topic, protected-history private streams). Assertions are set-membership checks on state, not exact-string or snapshot pins, so grading is deterministic and outcome-based (fail-before/pass-after)."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test exercises the pre-existing PATCH /json/messages/{id} message-move API and asserts outcomes via pre-existing interfaces: StreamTopicTarget.user_ids_with_visibility_policy, UserTopic.VisibilityPolicy, the existing automatically_follow_topics_policy / automatically_unmute_topics_in_muted_streams_policy settings, and the existing AUTOMATICALLY_CHANGE_VISIBILITY_POLICY_ON_INITIATION constant. It never references the new helper apply_automatic_unmute_follow_topics_policy or any other name/structure introduced by the fix, so it grades observable behavior only."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product intent clearly, and the expected-behavior evidence pins down the determinate rules: which sender qualifies (the one whose moved message becomes the destination topic's first message), the ordering rule when the destination already has messages, the protected-history access check, and that both the follow and unmute policies apply. Together these are concrete enough for independent compatible implementations."
}
