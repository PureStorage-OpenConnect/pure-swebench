# ZT-db94b3779e5d -- filter: Redirect `mentions:me` to `is:mentioned`.

- lang: web   issue: #34751   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/db94b3779e5dfb7eab8124e1613f0dc0fa55c8bc
- f2p: web/tests/filter.test.cjs, web/tests/hash_util.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "small well-specified improvement (web client search/narrow behavior)",
  "reason": "Behavioral change with observable effects through pre-existing interfaces: Filter term canonicalization and hash_util.parse_narrow now rewrite mentions:me to is:mentioned. Hidden tests can assert parsed narrow terms and suggestion output directly (e.g., parse_narrow on a #narrow/mentions/me hash yields {operator: 'is', operand: 'mentioned'}). Not a refactor, revert, docs, i18n, type-only, or test-only change, and nothing is time/version-gated."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "The tests call pre-existing APIs (Filter.convert_suggestion_to_term, Filter parsing, hash_util.parse_narrow \u2014 all already used in the surrounding test context at base) and assert only the behavioral outcome that mentions:me canonicalizes to the pre-existing is:mentioned term. No new symbols, error strings, or author-chosen names from the fix are referenced."
}
