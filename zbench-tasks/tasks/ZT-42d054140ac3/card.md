# ZT-42d054140ac3 -- integrations: Add repository name support to Github push messages.

- lang: py   issue: #34525   tier: B
- fix: https://github.com/zulip/zulip/commit/42d054140ac360fce98b46f1e064ee5fae9ab09a
- f2p: zerver.webhooks.github.tests.GitHubWebhookTest.test_commit_comment_msg, zerver.webhooks.github.tests.GitHubWebhookTest.test_push_1_commit_with_repository_name, zerver.webhooks.github.tests.GitHubWebhookTest.test_push_multiple_committers_with_repository_name
- p2p: zerver.tests.test_integrations

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, assignable feature: add an opt-in `include_repository_name` URL option to the GitHub webhook that changes push-notification message content. The hidden tests use Zulip's standard check_webhook pattern with fixed fixtures, so they are deterministic and fail-before/pass-after. Although they assert full message strings, the message text IS the observable behavior being changed (the repo name/link appearing in the notification), not incidental formatting \u2014 this is the codebase's conventional way to grade webhook output, not a brittle snapshot."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The GitHub webhook integration URL gains a new boolean query parameter named `include_repository_name` (parsed as JSON bool, e.g. `include_repository_name=true`; default false). It is appended to the webhook URL like existing options such as `ignore_private_repositories`.",
    "When `include_repository_name` is enabled, the push-event notification message's first line changes from '{user} [pushed]({compare_url}) {N} commit(s) to branch {branch}.' to '{user} [pushed]({compare_url}) {N} commit(s) to branch {branch} of [{repository_full_name}]({repository_html_url}).' \u2014 i.e. a Markdown link whose text is the repository's full name (from the payload's `repository.full_name`) and whose target is the repository's HTML URL (from `repository.html_url`). The rest of the message (commit list, truncation note, 'Commits by X (n), ...' committers detail) is unchanged.",
    "When the option is absent or false, push messages are byte-identical to the pre-existing format (existing tests must keep passing)."
  ],
  "reason": "The test exercises the feature purely through pre-existing public surfaces: the webhook endpoint via check_webhook and the pre-existing build_webhook_url test helper, which just adds query parameters to the URL. The only new names it binds to are (a) the URL option `include_repository_name`, a public settings/query-parameter name a ticket would legitimately dictate, and (b) the exact user-facing notification wording 'to branch X of [org/repo](url)', which is user-visible message content a spec can fully pin down. It does not reference internal helpers (get_repository_url, Helper fields, template constant names) or mock any internals, so with the above contract in the brief the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user problem clearly, and the evidence pins down the exact opt-in parameter name, its parsing/default, and the precise message format (including punctuation placement and interaction with the committers summary), so the outcome is determinate and checkable."
}
