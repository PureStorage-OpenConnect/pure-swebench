# ZT-215cc632bc6b -- mention: Skip fetching group membership for silent-mentioned groups.

- lang: py   issue: #32934   tier: B
- fix: https://github.com/zulip/zulip/commit/215cc632bc6b3bdc4c1fbfafe7f6d01a8403cf41
- f2p: zerver.tests.test_markdown.MarkdownMiscTest.test_invalid_katex_path, zerver.tests.test_markdown.MarkdownMiscTest.test_silent_mention_user_groups
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "performance optimization with observable behavior change",
  "reason": "The change alters observable behavior: silent group mentions no longer fetch group membership, so MentionData.get_group_members returns an empty set for silently-mentioned groups. The hidden tests assert this outcome deterministically (membership sets and the silent/non-silent mention-type mapping, including precedence when the same group is mentioned both ways), failing before the fix and passing after. No snapshot pinning, exact-string brittleness, or format-over-behavior grading; this is a realistic assigned optimization task with a clear spec from the issue."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The function possible_user_group_mentions(content) in zerver/lib/mention changes its return type from a set of group names to a dict mapping each user-group name mentioned in the content to a mention-type string: 'silent' for groups mentioned only with the silent syntax @_*name*, and 'non-silent' for groups mentioned with the regular syntax @*name*.",
    "When the same group is mentioned both silently and non-silently in the same content, its dict entry must be 'non-silent', regardless of whether the silent or non-silent mention appears first.",
    "Group membership must not be fetched for groups that are only silently mentioned: for such groups, MentionData.get_group_members(group_id) returns an empty set, while groups with at least one non-silent mention return their full (recursive) membership as before."
  ],
  "reason": "The behavioral assertions go through the pre-existing MentionData.get_group_members interface. The only new binding is the revised return contract of possible_user_group_mentions \u2014 an existing, already-directly-tested module-level function \u2014 including its dict shape, the sentinel strings 'silent'/'non-silent', and the non-silent-wins precedence rule. That is interface surface a design brief would legitimately dictate; with those requirements in hand the test measures correctness, not guessing of internal choices."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue alone is vague about the concrete optimization, but the expected-behavior evidence and interface requirements pin down a determinate, checkable outcome: possible_user_group_mentions returns a name\u2192{'silent','non-silent'} dict with non-silent precedence, and MentionData skips membership fetching (returning an empty set from get_group_members) for silently-only-mentioned groups while preserving full recursive membership for non-silent ones. Two engineers given this brief would produce compatible implementations."
}
