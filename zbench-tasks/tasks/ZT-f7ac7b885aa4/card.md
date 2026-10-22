# ZT-f7ac7b885aa4 -- narrow: Handle use of -is:dm with channels:public.

- lang: py   issue: #33033   tier: B
- fix: https://github.com/zulip/zulip/commit/f7ac7b885aa430c577f3f66fe5045059528bc33b
- f2p: zerver.tests.test_message_fetch.NarrowBuilderTest.test_add_term_using_dm_operator_not_the_same_user_as_operand_and_negated, zerver.tests.test_message_fetch.NarrowBuilderTest.test_combined_channel_dm, zerver.tests.test_message_fetch.NarrowBuilderTest.test_combined_channel_with_negated_is_dm, zerver.tests.test_message_fetch.NarrowBuilderTest.test_combined_negated_channel_with_is_dm, zerver.tests.test_message_fetch.NarrowBuilderTest.test_negated_is_dm_with_dm_operator
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real user-reported search bug (-is:dm broke with channels:public) fixed in narrow-building logic. The hidden tests grade observable behavior deterministically: they assert that specific narrow-term combinations either raise BadNarrowOperatorError or build successfully. The one pinned string is a short, stable error message, not a snapshot \u2014 tests fail before the fix and pass after, with no format brittleness."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The hidden test uses only interfaces present at the base commit: NarrowParameter (with its existing negated flag), the pre-existing _build_query helper, BadNarrowOperatorError, and an error message string already asserted verbatim by the neighboring test_combined_channel_dm. It asserts purely behavioral outcomes \u2014 that a negated is:dm narrow raises the existing channel/dm-conflict error when combined with a dm operator, and does not raise when combined with channel operators. The reference fix's internal choice (adding a maybe_negate parameter to check_not_both_channel_and_dm_narrow) is never touched by the test, so no author-only names or implementation choices must be guessed."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the user-visible symptom (empty results for channels:public with -is:dm) and the expected outcome; the evidence pins down the exact semantics for negated terms, including the new conflict case (-is:dm with dm:) and the exact error message, giving a determinate, checkable specification."
}
