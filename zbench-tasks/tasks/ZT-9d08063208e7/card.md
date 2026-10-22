# ZT-9d08063208e7 -- webhooks/github: Added support for issue transferred events.

- lang: py   issue: #33450   tier: B
- fix: https://github.com/zulip/zulip/commit/9d08063208e799fe0a29eaa6645d09cbffa40bba
- f2p: zerver.webhooks.github.tests.GitHubWebhookTest.test_issue_transfer_opened_message, zerver.webhooks.github.tests.GitHubWebhookTest.test_issue_transfer_transferred_message, zerver.webhooks.github.tests.GitHubWebhookTest.test_membership_msg
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix / integration feature",
  "reason": "Real assigned-work bug fix: GitHub webhook mishandled transferred-issue events, reporting them as 'opened'. The hidden grader is Zulip's standard webhook test pattern \u2014 feed a recorded JSON fixture through the endpoint and assert the topic and short one-line message body. That message body IS the observable behavior (what the bot posts), not an incidental long snapshot, and the check fails before the fix (wrong 'opened' message) and passes after. Deterministic, outcome-based, not format-brittle."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When the GitHub webhook receives an issues event with action `transferred`, the integration must post the message: \"{sender} transferred [issue #{old_issue_number} {title}]({old_issue_html_url}) to [{new_repo_full_name}/#{new_issue_number}]({new_issue_html_url}).\" \u2014 old issue number/title/URL taken from payload `issue`, new repo full name and new issue number/URL taken from payload `changes.new_repository` and `changes.new_issue`.",
    "When the GitHub webhook receives an issues event with action `opened` whose payload contains `changes.old_issue` (an issue created by a transfer), the integration must post the message: \"[Issue #{issue_number} {title}]({issue_html_url}) was transferred from {old_repo_full_name}.\" \u2014 using the payload's `issue` fields and `changes.old_repository.full_name`, instead of the normal issue-opened message.",
    "These two cases are exposed as distinct user-facing event types named `issues_transferred` and `issues_opened_via_transfer` in the webhook's supported-event list (usable in the URL's event-filtering parameter).",
    "The messages go to the topic following the integration's existing convention for issue events: \"{repo name} / issue #{issue number} {issue title}\"."
  ],
  "reason": "The test exercises the pre-existing GitHub webhook endpoint with new payload fixtures and asserts only user-visible outcomes: the posted message text and topic. The bindings to new surface are the exact message wording and the event-type names \u2014 both product-level contract a ticket would legitimately dictate for a chat-integration feature. No private helper names, internal call signatures, or mock targets are referenced, so a solver handed these requirements would be graded on correctness, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the user-visible bug and desired direction; the payload evidence pins down the exact field paths (top-level issue vs. changes.old_issue/old_repository/new_issue/new_repository) and the distinguishing condition for a transfer-created 'opened' event; the interface requirements fix the exact message formats, event-type names, and topic convention. Together these give a determinate, checkable outcome for both event variants plus the unchanged genuine-open case."
}
