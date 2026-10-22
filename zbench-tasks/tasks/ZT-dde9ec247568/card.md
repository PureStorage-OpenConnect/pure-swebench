# ZT-dde9ec247568 -- webhooks/github: Improve coverage for pull-request events.

- lang: py   issue: #34223   tier: B
- fix: https://github.com/zulip/zulip/commit/dde9ec2475687569196f1712fad00e23eab3c667
- f2p: zerver.webhooks.github.tests.GitHubWebhookTest.test_check_run, zerver.webhooks.github.tests.GitHubWebhookTest.test_pull_request_converted_to_draft_msg, zerver.webhooks.github.tests.GitHubWebhookTest.test_pull_request_demilestoned_msg, zerver.webhooks.github.tests.GitHubWebhookTest.test_pull_request_dequeued_msg, zerver.webhooks.github.tests.GitHubWebhookTest.test_pull_request_enqueued_msg, zerver.webhooks.github.tests.GitHubWebhookTest.test_pull_request_labeled_msg, zerver.webhooks.github.tests.GitHubWebhookTest.test_pull_request_milestoned_msg, zerver.webhooks.github.tests.GitHubWebhookTest.test_pull_request_reopened_msg, zerver.webhooks.github.tests.GitHubWebhookTest.test_pull_request_review_request_removed_msg, zerver.webhooks.github.tests.GitHubWebhookTest.test_pull_request_unlabeled_msg
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real behavior change: previously-ignored GitHub pull-request actions (converted_to_draft, labeled/unlabeled, review_request_removed, milestoned/demilestoned, enqueued/dequeued) now produce Zulip notification messages, and 'reopened' PRs now include branch info. This is a plausible integration-improvement assignment. The hidden tests follow Zulip's standard webhook pattern: post a recorded JSON fixture and assert the short generated message string, which IS the observable outcome and is fully deterministic. The asserted strings are one-line notification messages, not long snapshots, so this is behavior-graded, fail-before/pass-after verifiable."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The GitHub integration stops ignoring the pull_request action `converted_to_draft` and posts the message: \"{sender} converted [PR #{number} {title}]({pr_html_url}) to a draft.\"",
    "The GitHub integration stops ignoring the pull_request action `review_request_removed` and posts the message: \"{sender} unassigned {requested_reviewer_login} from [PR #{number} {title}]({pr_html_url}).\"",
    "The GitHub integration stops ignoring the pull_request actions `labeled` and `unlabeled` and posts: \"{sender} added the label `{label_name}` on [PR #{number}]({pr_html_url}).\" for labeled, and \"{sender} removed the label `{label_name}` from [PR #{number}]({pr_html_url}).\" for unlabeled (label name in backticks, message omits the PR title).",
    "The GitHub integration handles the pull_request actions `milestoned` and `demilestoned`, posting: \"{sender} linked [PR #{number}]({pr_html_url}) to the milestone `{milestone_title}`.\" for milestoned (milestone title read from pull_request.milestone.title) and \"{sender} unlinked [PR #{number}]({pr_html_url}) from the milestone `{milestone_title}`.\" for demilestoned (milestone title read from the top-level milestone object); these messages omit the PR title.",
    "The GitHub integration handles the pull_request actions `enqueued` and `dequeued`, posting: \"{sender} added [PR #{number} {title}]({pr_html_url}) to the merge queue.\" and \"{sender} removed [PR #{number} {title}]({pr_html_url}) from the merge queue.\" respectively.",
    "Messages for reopened pull requests include the source and destination branch labels (head and base, e.g. \"from `owner:branch` to `owner:base`\"), the same way opened and merged PR messages already do.",
    "All of these notifications go to the integration's existing per-PR topic convention (e.g. \"{repo} / PR #{number} {title}\"), unchanged from current behavior."
  ],
  "reason": "The hidden test exercises the integration through the pre-existing webhook endpoint with new GitHub payload fixtures (which ship with the test itself) and asserts the resulting topic and message strings \u2014 all user-visible outcomes. It does not reference the new handler function names, the EVENT_FUNCTION_MAPPER/PULL_REQUEST_ACTION_TO_EVENT keys, or the internal `suffix` parameter added to get_pull_request_event_message; those remain free implementation choices. What the test does pin is the exact user-facing message wording for each newly-supported pull_request action, which a ticket for a chat-notification integration would legitimately dictate. With the message formats above supplied in the brief, the test grades behavioral correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue names the sub-events and files involved, and the interface requirements pin down exact message wording, payload fields to read (e.g. milestone location differs between milestoned/demilestoned), link-text variations (title omitted for label/milestone messages), the reopened branch-label requirement, and the unchanged topic convention \u2014 enough for two engineers to independently produce compatible implementations."
}
