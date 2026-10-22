# ZT-d94ba5e45bb8 -- gitlab: Add deployment webhooks.

- lang: py   issue: #34220   tier: B
- fix: https://github.com/zulip/zulip/commit/d94ba5e45bb85313af39aa3381ff3ef29eccdb74
- f2p: zerver.webhooks.gitlab.tests.GitlabHookTests.test_deployment_canceled_event_message, zerver.webhooks.gitlab.tests.GitlabHookTests.test_deployment_failed_event_message, zerver.webhooks.gitlab.tests.GitlabHookTests.test_deployment_started_event_message, zerver.webhooks.gitlab.tests.GitlabHookTests.test_deployment_succeeded_event_message
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature (webhook integration event support)",
  "reason": "Real, commonly-assigned integration work: add GitLab Deployment Hook support with an event-body function and topic logic. The hidden test uses Zulip's standard check_webhook pattern with static JSON fixtures, grading the observable outcome (topic name and message content) deterministically \u2014 fails before the change (unknown event) and passes after. The expected messages are short, fixture-derived strings reflecting the specified behavior, not a fragile long snapshot or non-deterministic formatting."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "Support the GitLab 'Deployment Hook' webhook event (the value GitLab itself sends in the X-Gitlab-Event header for deployment events; test fixtures named deployment_hook__<status>.json map to this header via the existing fixture-to-header convention).",
    "Topic name for deployment events: '<project name> / <environment>' (e.g. 'test / production'), taking the project name from payload.project.name and the environment from payload.environment.",
    "Message for status 'running': '[<user name>](<user_url>) started a new [deployment](<deployable_url>):\\n> [<short sha>](<commit_url>) <commit_title>' \u2014 user name/URL from payload.user.name and payload.user_url, deployment link from payload.deployable_url, quoted line links the commit.",
    "Short sha in the running message: first 7 characters of the commit SHA (derived from the commit URL's final path segment), e.g. '5879366'.",
    "Message for status 'success': 'The [deployment](<deployable_url>) was successful.'",
    "Message for status 'failed': 'The [deployment](<deployable_url>) failed.'",
    "Message for status 'canceled': 'The [deployment](<deployable_url>) was canceled.'",
    "The word 'deployment' is rendered as a markdown link to payload.deployable_url in all four messages (plain text 'deployment' if the URL is absent)."
  ],
  "reason": "The test uses only the pre-existing check_webhook harness (POST fixture payload, assert topic and message), so it exercises user-visible outcomes rather than internal helpers \u2014 no mocks, no private function names, no internal data structures. What it binds to is the exact user-facing message text and topic format for a new event type, plus fixture filenames that follow the repo's established <event>__<variant> convention mapping to GitLab's own event header. Exact bot-message wording and topic format are precisely what a Zulip integration ticket would dictate (all existing GitLab event handlers in this file are specified this way), so with the contract above a solver is graded on correctness, not name-guessing. It is not 'clean' because the event handler, topic format, and message templates are all new surface introduced by this change."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue names the feature and the affected files, and the evidence pins down the exact observable outputs: the event header, payload shape for all four statuses, topic format ('test / production'), and the precise message text for each status. Combined with the verbatim interface requirements, two engineers working independently would produce compatible implementations."
}
