# ZT-9fd5f36c6d0c -- webhooks: Add option to ignore events from private GitLab Projects.

- lang: py   issue: #31766   tier: B
- fix: https://github.com/zulip/zulip/commit/9fd5f36c6d0ce06ab4fcd8464f9936ce498124a5
- f2p: zerver.webhooks.gitlab.tests.GitlabHookTests.test_merge_request_merged_event_message_ignored, zerver.webhooks.gitlab.tests.GitlabHookTests.test_push_event_private_project_ignored, zerver.webhooks.gitlab.tests.GitlabHookTests.test_push_local_branch_without_commits, zerver.webhooks.gitlab.tests.GitlabHookTests.test_wiki_page_opened_event_message
- p2p: zerver.tests.test_integrations

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Real integration feature (a new ignore_private_projects URL option for the GitLab webhook) with a clear observable outcome: when the option is set and the payload's project visibility_level is private, the webhook returns a no-op instead of posting a message. The hidden tests grade exactly that behavior via check_webhook(..., expect_noop=True) using existing fixtures \u2014 deterministic and fail-before/pass-after, with no snapshot pinning or exact-string brittleness in the new assertions."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "the GitLab webhook URL gains a boolean query parameter `ignore_private_projects` (e.g. ?ignore_private_projects=true): when set to true, events from private GitLab projects (payload project visibility_level == 0, i.e. private) are silently ignored \u2014 the endpoint returns success but sends no message",
    "the ignore behavior applies to all event types carrying project visibility info, including push events and merge-request events (the shipped fixtures `push_hook` and `merge_request_hook__merge_request_merged` describe private projects and must produce no message when the option is enabled)"
  ],
  "reason": "The test's only new binding is the `ignore_private_projects` URL option name and its noop semantics \u2014 public, user-facing contract a ticket would dictate (mirroring GitHub's existing ignore_private_repositories option). All other surface (build_webhook_url, check_webhook, expect_noop, fixtures) pre-exists at base. No internal names, signatures, or wording are coupled."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the goal (filter private-project activity in the GitLab webhook, mirroring the GitHub feature), and the expected-behavior evidence plus interface requirements pin down the exact parameter name (ignore_private_projects), the trigger condition (project visibility_level == 0), the silent-success semantics, and the event types that must be covered. That is enough for two engineers to independently build compatible implementations."
}
