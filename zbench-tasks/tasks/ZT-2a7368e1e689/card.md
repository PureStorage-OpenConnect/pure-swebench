# ZT-2a7368e1e689 -- search: Allow adding users to dm-including pills.

- lang: web   issue: #33342   tier: B
- fix: https://github.com/zulip/zulip/commit/2a7368e1e689d57350466cb6bd6af05718016ee1
- f2p: web/tests/message_view.test.cjs
- p2p: web/tests/filter.test.cjs, web/tests/search_suggestion.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix / behavior change (frontend search)",
  "reason": "Real, assignable engineering task (high-priority labeled bug): extend dm-including narrows to support multiple comma-separated users across filtering, suggestions, message fetch, and empty-narrow banners. The observable behavior clearly changes (multi-user operands previously matched nothing / errored), so a test can fail-before/pass-after. The hidden test asserts a short, targeted translated banner string for a nonexistent-user case via Zulip's standard empty_narrow_html helper \u2014 deterministic and behavior-focused, not a full-page snapshot or incidental-format pin. Note: the truncated code diff shows a generic 'This user does not exist!' message while the test expects the email-specific variant, likely resolved in a truncated portion of the diff; this is a spec detail for later stages, not a verifiability failure."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The `dm-including` search/narrow operator must accept a comma-separated list of user emails as its operand (e.g. `dm-including:a@x.com,b@y.com`), matching messages whose direct-message recipients include all of the listed users.",
    "When an empty-narrow banner is rendered for a `dm-including` filter whose operand contains multiple comma-separated emails and at least one email does not correspond to an existing user, the banner title must be the user-facing message 'User {email} does not exist!', where {email} is the nonexistent email address (e.g. 'User false@blah.com does not exist!'). The pre-existing single-operand wording 'This user does not exist!' is retained for the single-email case."
  ],
  "reason": "The test exercises the feature entirely through pre-existing interfaces: it builds a Filter via the existing set_filter helper and calls the existing narrow_banner.show_empty_narrow_message, asserting the rendered banner HTML. It binds to no new function names, module layout, or internal helpers (people.pm_with_operand_ids etc. are never referenced by the test). The only new surface it pins is (a) that dm-including accepts a comma-separated multi-email operand \u2014 the feature itself \u2014 and (b) the exact user-facing error string for a nonexistent user in a multi-email operand. User-visible message wording is exactly the kind of detail a ticket legitimately dictates, so with these two items in the brief the test grades correctness rather than name-guessing. Note: the truncated reference diff shows a non-specific 'This user does not exist!' for the multi-email case, while the test expects the email-specific wording; the contract item above records what the test actually asserts, which the brief must therefore specify."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product goal (multi-user dm-including pills and operator), and the evidence plus interface requirements pin down the observable semantics: comma-separated email operands with all-listed-users-included matching, and exact empty-narrow banner wording for both single-email ('This user does not exist!') and multi-email ('User {email} does not exist!') cases. This is determinate and checkable by two independent engineers."
}
