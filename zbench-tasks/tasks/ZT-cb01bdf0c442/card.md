# ZT-cb01bdf0c442 -- topics: Follow topics that are merged into even after merge.

- lang: py   issue: #35226   tier: B
- fix: https://github.com/zulip/zulip/commit/cb01bdf0c44226ae4b30656861826ebcd0a9f65c
- f2p: zerver.tests.test_message_move_topic.MessageMoveTopicTest.test_merge_user_topic_states_on_move_messages
- p2p: zerver.tests.test_message_edit

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned bug: merging a followed topic dropped the FOLLOWED visibility policy. The hidden test grades observable outcomes deterministically \u2014 it exercises topic moves via check_update_message and asserts resulting per-user UserTopic visibility policies (INHERIT/MUTED/UNMUTED/FOLLOWED) across a matrix of cases. It fails before the fix and passes after, asserts state rather than exact strings or snapshots, and has no time/version gating or formatting brittleness."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test asserts only user-visible behavior (a user's resulting topic visibility policy after a topic move) through interfaces that all exist at the base commit: do_set_user_topic_visibility_policy, check_update_message, the assert_has_visibility_policy helper, and the pre-existing UserTopic.VisibilityPolicy.FOLLOWED enum value (the code diff uses FOLLOWED without introducing it). It never references the internal get_visibility_policy_after_merge helper or any name invented by the fix; a solver need only make FOLLOWED policies merge correctly during topic moves, which is the bug itself, not an implementation choice."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_message_move_topic.MessageMoveTopicTest.test_merge_user_topic_states_on_move_messages"
  ],
  "reason": "All hunks fall within a single existing test method \u2014 the diff adds a fourth user (shiva) and FOLLOWED visibility-policy cases (including a new Topic4 block) to the merge-on-move test. Verified against the upstream zulip/zulip file that the modified lines (shiva setup, FOLLOWED tables, Topic4 section) are inside MessageMoveTopicTest.test_merge_user_topic_states_on_move_messages; no test methods were added or removed."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives a clear user-facing bug, and the expected-behavior evidence provides the exact merge matrix for all policy combinations including the new FOLLOWED rows, plus the requirement that source-topic policies reset to INHERIT. Together they define a determinate, checkable outcome. There are no interface requirements to include."
}
