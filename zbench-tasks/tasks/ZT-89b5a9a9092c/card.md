# ZT-89b5a9a9092c -- message-move: Improve time limit error for "change_all" moves.

- lang: py   issue: #38930   tier: B
- fix: https://github.com/zulip/zulip/commit/89b5a9a9092c7d60c7c3ed1bc6c789c536862898
- f2p: zerver.tests.test_message_move_topic.MessageMoveTopicTest.test_notify_new_topic
- p2p: zerver.tests.test_message_edit

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix / behavior improvement",
  "reason": "Real behavior change: 'change_all' moves no longer hit the per-message edit deadline check and get a clearer, accurate error when no messages can be moved. The hidden tests grade observable API outcomes deterministically \u2014 JSON error responses and message counts before/after \u2014 and would fail before the fix and pass after. Asserting short user-facing error strings is standard practice, not a brittle snapshot pin."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "For non-moderator users in realms with a message-move time limit, a move request with propagate_mode 'change_all' must not be rejected by the per-message edit/move deadline check; only the topic-wide recency limit applies, so the request may reference any message in the topic (including one older than the deadline).",
    "When a 'change_all' move is partially blocked by the time limit, the request fails with the existing user-facing error 'You only have permission to move the N/M most recent messages in this topic.', where M is the total number of messages in the topic and N is how many fall within the time limit \u2014 these counts must be reported even when the message id named in the request is itself outside the limit, and the topic's messages must be left unmoved.",
    "When a 'change_all' move is fully blocked because zero messages in the topic fall within the time limit, the request fails with the user-facing error 'The time limit for moving this topic has passed.' (replacing the previous wording 'The time limit for editing this message's topic has passed.')."
  ],
  "reason": "The test exercises only pre-existing surface: the PATCH /json/messages/{id} endpoint, the propagate_mode request parameter, the response field first_message_id_allowed_to_move, and the 'You only have permission to move the N/M most recent messages' error string (all present as context at the base commit). The new bindings are purely user-facing behavior and one new error message: change_all moves skip the per-message deadline check, partial blocks report counts instead of rejecting outright when an older message id is used, and a fully-expired topic yields the reworded time-limit error. All of these are outcomes and message wording a ticket would legitimately dictate; no private helpers, mock targets, or internal structure are referenced."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue is thin, but the expected-behavior evidence and interface requirements together pin down a determinate, checkable outcome: for change_all moves the per-message deadline check is skipped, partial blocks always report the N/M error with counts and leave messages unmoved (even when the named message is too old), and full blocks use the new wording 'The time limit for moving this topic has passed.' change_one behavior is explicitly preserved."
}
