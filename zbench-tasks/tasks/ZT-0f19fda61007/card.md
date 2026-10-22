# ZT-0f19fda61007 -- filter: Mark messages as read in -is:dm view.

- lang: web   issue: #25113   tier: B
- fix: https://github.com/zulip/zulip/commit/0f19fda61007caab331d002a273a2671569a413f
- f2p: web/tests/filter.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix / behavior change",
  "reason": "Real user-facing behavior change: messages in the -is:dm search view become markable as read. The hidden test constructs a Filter with the negated is:dm term and asserts boolean predicate outcomes (can_mark_messages_read, can_apply_locally, etc.) \u2014 deterministic, fails before the fix and passes after, with no string/snapshot pinning or format brittleness."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The added test constructs a Filter with the pre-existing public term shape ({operator: 'is', operand: 'dm', negated: true}) and asserts against Filter methods (can_mark_messages_read, contains_only_private_messages, is_conversation_view, etc.) that all exist at the base commit \u2014 the identical assertion block appears immediately above for other term sets. The reference fix only changes the behavior of the existing can_mark_messages_read method for the negated is:dm view (via the internal 'not-is-dm' term-type, which the test never references). The test grades a user-visible behavioral outcome through pre-existing interfaces; no new names or internal choices must be guessed."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the intended product rule clearly, and the expected-behavior evidence pins down the exact observable classification of the negated is:dm narrow (mark-as-read eligible, locally applicable, no partial conversations, not a conversation/channel/personal view), which is enough for two engineers to build compatible implementations."
}
