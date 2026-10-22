# ZT-08ed63976323 -- filter: Validate and parse sender:me when turning into a pill.

- lang: web   issue: #31315   tier: B
- fix: https://github.com/zulip/zulip/commit/08ed639763232ff8c4a692670f56bf2cbe300db7
- f2p: web/tests/filter.test.cjs
- p2p: web/tests/search.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real bug fix with observable behavior: parsing 'sender:me' (with for_pills) resolves to the current user's email and validates as a search term. The hidden test asserts parsed term objects and a boolean validity outcome \u2014 deterministic, small, behavior-focused assertions, not brittle snapshots or exact-string pins. Fails before the fix, passes after."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "Filter.parse gains an optional second boolean parameter (defaulting to false) that enables search-pill parsing mode; callers pass it positionally as the second argument, and omitting it preserves the existing parsing behavior exactly",
    "When that second parameter is true and a term's operator is `sender` with operand `me` (case-insensitive, with or without negation), Filter.parse resolves the operand to the current user's email address, producing e.g. {operator: 'sender', operand: '<current user's email>'} and preserving the `negated` flag",
    "Search-term validation (the existing is_valid_search_term behavior) must accept the literal operand `me` as valid for person-based operators such as `sender`, even though `me` is not a registered user email"
  ],
  "reason": "The test binds to one new surface: an optional second boolean argument on the pre-existing public API Filter.parse. It is used only positionally, so no internal name is guessed; a ticket could legitimately specify 'Filter.parse takes an optional flag for pill-context parsing where sender:me resolves to the current user'. All other assertions go through pre-existing interfaces (Filter.parse output terms, is_valid_search_term) and check user-visible outcomes: 'me' resolving to the logged-in user's email and validating as a sender operand. The test does not stub internals or depend on people.my_current_email or the for_pills identifier by name, so with the listed requirements in the brief the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the user-visible bug, and the expected-behavior evidence plus interface requirements pin down the exact contract: a positional boolean pill-mode flag on Filter.parse, case-insensitive resolution of the 'me' operand for sender (with negation preserved) to the current user's email, unchanged default parsing, and validation accepting 'me' for person operators. This is determinate and independently checkable."
}
