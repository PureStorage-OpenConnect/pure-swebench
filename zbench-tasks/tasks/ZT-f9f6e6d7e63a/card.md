# ZT-f9f6e6d7e63a -- mention: Optimize query when mentioning several groups.

- lang: py   issue: #32934   tier: B
- fix: https://github.com/zulip/zulip/commit/f9f6e6d7e63aea9534113721044ff01a90e032ac
- f2p: zerver.tests.test_markdown.MarkdownMiscTest.test_bulk_user_group_mentions
- p2p: zerver.tests.test_user_groups

## screen: suitability
{
  "verdict": "keep",
  "task_type": "performance-optimization",
  "reason": "Real engineering task (issue-driven query optimization with a nontrivial recursive-CTE rewrite). The hidden test grades the observable outcome deterministically: database query count drops from 41 (linear in mentioned groups) to a constant 2 via Zulip's standard assert_database_query_count harness. Query counts are deterministic in this test setup and fail-before/pass-after cleanly. Pinning the exact count is the behavior under test, not incidental formatting \u2014 this is not a snapshot/string-pin brittleness case."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "Constructing MentionData for message content that mentions user groups must issue a constant number of database queries regardless of how many groups are mentioned (no per-group query fan-out)",
    "That constant must be exactly 2 queries for the group-mention resolution path: one query to look up the mentioned NamedUserGroup rows by name, and one bulk query that resolves the recursive (transitive) active membership of all mentioned non-deactivated groups at once"
  ],
  "reason": "The test touches no new names: it exercises the pre-existing MentionData constructor and the pre-existing assert_database_query_count harness, so there is no binding to private helpers, mocks, or internal field names (the new get_root_id_annotated_recursive_subgroups_for_groups helper is never referenced by the test). The only coupling is the literal query count of 2. That is not fully derivable from 'make it O(1)': a solver could write a correct constant-query solution that uses 1 or 3 queries and fail. However, an exact query budget is a legitimate performance requirement a ticket can state ('resolve all group mentions in one name-lookup query plus one bulk recursive-membership query'), and with that requirement in the brief the test grades correctness rather than guesswork. Hence specifiable, not clean and not coupled."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_markdown.MarkdownMiscTest.test_bulk_user_group_mentions"
  ],
  "reason": "The diff only touches the query-count assertion inside MarkdownMiscTest.test_bulk_user_group_mentions in zerver/tests/test_markdown.py (replacing UNFORTUNATE_QUERY_COUNT = 41 with CONSTANT_QUERY_COUNT = 2); no other test methods are added or changed \u2014 test_invalid_katex_path appears only as unchanged context."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue plus the observable-behavior evidence and interface requirements pin down a determinate, checkable outcome: MentionData construction must resolve group mentions in exactly 2 constant queries (name lookup + one bulk recursive-membership query) with unchanged membership semantics. Two engineers could independently implement compatible solutions (e.g., a recursive CTE) and verify via query counts and per-group membership equality."
}
