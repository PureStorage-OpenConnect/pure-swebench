# ZT-09f47d5a0ac3 -- webhooks/github: Suppress "comment edited" events when body is same.

- lang: py   issue: #31042   tier: B
- fix: https://github.com/zulip/zulip/commit/09f47d5a0ac38ffeb9993ef91b1a8e2b5d293dbd
- f2p: zerver.webhooks.github.tests.GitHubWebhookTest.test_comment_edited_unchanged_skipped
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, well-scoped integration bug (GitHub webhook sends a spurious 'edited' notification when a comment is hidden/unchanged) with a clear fail-before/pass-after outcome: given the new issue_comment__edited__unchanged fixture, the webhook must produce no Zulip message. The hidden grader checks that the event is ignored \u2014 a deterministic behavioral assertion, not a pinned output string or snapshot. The large diffstat is almost entirely the replayed webhook payload fixture, which is standard for Zulip webhook tests and not brittle."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test adds a new GitHub webhook fixture (an issue_comment 'edited' payload where changes.body.from equals the current comment body) and exercises it through the pre-existing GitHub webhook endpoint (/api/v1/external/github) using Zulip's standard webhook test harness. The asserted outcome is purely user-visible behavior on an existing interface: the event is accepted (HTTP success) but produces no Zulip message. It does not reference any new function names, helper signatures, settings, fields, or log wording introduced by the fix \u2014 the fix is entirely internal control flow in api_github_webhook. Any correct implementation that suppresses no-op comment-edit notifications would pass; nothing requires guessing author-specific choices."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the user-visible bug (hidden comments reported as 'edited'), and the expected-behavior evidence pins down the exact payload signature (an issue_comment edited event whose changes.body.from equals comment.body, fixture named 'edited unchanged') and the required outcome (no message sent). Together these yield a determinate, checkable specification."
}
