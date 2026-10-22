# ZT-5c7a7740265e -- typeahead_helper: Place bots under group matches.

- lang: web   issue: #32987   tier: B
- fix: https://github.com/zulip/zulip/commit/5c7a7740265eec8e5d10e996070dff452f7c99b8
- f2p: web/tests/composebox_typeahead.test.cjs, web/tests/typeahead_helper.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior change (typeahead sort-order fix)",
  "reason": "Real, well-scoped UX bug fix: bots should sort below group matches in @-mention typeahead. The behavior is deterministic sorting logic in sort_recipients, and the hidden test grades exactly that observable outcome \u2014 ordered lists of result identifiers from small fixture inputs. Asserting exact order is the correct (not brittle) way to test a sort-order change; it fails before the fix and passes after, with no snapshot/formatting or non-deterministic dependence."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test asserts only the user-visible ordering of typeahead suggestions via the pre-existing sort_recipients/get_typeahead_result interface, plus adding the pre-existing User field is_bot to fixtures. It never references the fix's internal names (bot partitioning helper, best_bots/ok_bots/worst_bots tiers); any implementation that ranks bots below equally-relevant human users passes."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the headline requirement directly (bots after user groups in @-mention typeahead), and the expected-behavior evidence pins down the concrete sorting semantics: within each existing relevance bucket of the recipient sort, non-bot users now precede bot users (e.g. exact email match first, then remaining humans, then bots), with intra-group order otherwise unchanged, and classification driven by the is_bot flag. Together these give a determinate, checkable outcome two engineers would implement compatibly."
}
