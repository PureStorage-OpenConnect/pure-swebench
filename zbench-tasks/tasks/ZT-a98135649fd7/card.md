# ZT-a98135649fd7 -- deactivated_user: Show deactivated status for deactivated users.

- lang: web   issue: #26833   tier: B
- fix: https://github.com/zulip/zulip/commit/a98135649fd764df7b34f82c105abf2cf1849e5e
- f2p: web/tests/message_list_view.test.cjs, web/tests/people.test.cjs, web/tests/pm_list_data.test.cjs
- p2p: web/tests/input_pill.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real UI feature (show deactivated status for users) with a data-layer surface that grades deterministically: hidden tests assert new observable behavior in people.sender_is_deactivated (true for deactivated sender, false otherwise) and the new is_deactivated field in pm_list_data display objects. Tests fail before the change (function/field don't exist) and pass after. Assertions are on structured logic outputs, not rendered HTML snapshots, exact long strings, or browser layout \u2014 the CSS/template icon changes are incidental and ungraded."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The `people` module exports a new function `sender_is_deactivated(message): boolean` \u2014 returns true iff the message's sender is a deactivated user, and false when `message.sender_id` is missing/undefined (mirroring the existing `sender_is_bot` / `sender_is_guest` helpers).",
    "Message-list rendering obtains each sender's deactivation status via `people.sender_is_deactivated(message)` and exposes it as a boolean field `sender_is_deactivated` on the per-message template data (MessageContainer), alongside the existing `sender_is_bot` and `sender_is_guest` fields.",
    "The display objects returned by `pm_list_data.get_conversations()` gain a boolean field `is_deactivated` \u2014 true when the DM conversation is with a deactivated user, false otherwise (including for group DMs and bot conversations with active users)."
  ],
  "reason": "The tests bind only to new names on surfaces Zulip treats as module-level API: `people.sender_is_deactivated` is a public export of the shared `people` module following the exact naming pattern of the pre-existing `sender_is_bot`/`sender_is_guest` (which the same tests already exercise), and its behavioral assertions (true for deactivated sender, false for active, false for undefined sender_id) are semantics a ticket would state. The `message_list_view` test's people-module stub follows the file's pre-existing stubbing of the sibling helpers, so it only requires that rendering route through the specified public function \u2014 a requirement a brief can state as a caller obligation. The `is_deactivated` field is asserted on the return value of the pre-existing exported `get_conversations()`, i.e., a new field on an existing public output shape. No private helpers, internal call signatures, or invented module layout are pinned; handed these three requirements, a solver would be graded on correct behavior, not name-guessing. Notably, the tests do not constrain the CSS classes, icons, or template details of the actual UI treatment, which is where most implementation freedom lies."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives concrete UI placement rules, and the evidence plus interface requirements pin down the exact module-level contracts (people.sender_is_deactivated semantics including the undefined-sender case, the sender_is_deactivated field on message template data, and the is_deactivated field on pm_list_data.get_conversations() results), so two engineers would independently produce compatible implementations."
}
