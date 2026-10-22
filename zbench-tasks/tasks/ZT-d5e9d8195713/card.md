# ZT-d5e9d8195713 -- integrations: Add support for GitLab access token expiry events.

- lang: py   issue: #34405   tier: B
- fix: https://github.com/zulip/zulip/commit/d5e9d81957131663bfc48fd40f80672275c05cf9
- f2p: zerver.webhooks.gitlab.tests.GitlabHookTests.test_resource_access_token_group_expiry, zerver.webhooks.gitlab.tests.GitlabHookTests.test_resource_access_token_project_expiry
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature (webhook event coverage)",
  "reason": "Adds handling for a new GitLab webhook event type \u2014 a realistic assignable integration task. The hidden test uses Zulip's standard check_webhook pattern with deterministic JSON fixtures, asserting the topic and the short bot message the handler produces. That message string IS the observable outcome of the change (not an incidental long snapshot), and it fails before/passes after deterministically. No format brittleness beyond the intended output template."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The GitLab webhook integration must handle the GitLab event delivered with the X-GitLab-Event header 'Resource Access Token Hook' (payload has object_kind 'access_token' and event_name 'expiring_access_token'), producing a Zulip notification message instead of ignoring or erroring on the event.",
    "The notification message for an expiring resource access token must be exactly: 'The access token [{name}]({url}) will expire on {date}.', where {name} is the payload's object_attributes.name rendered as a Markdown link.",
    "The link {url} must point to the resource's access-token settings page: for a project token, '{project.web_url}/-/settings/access_tokens'; for a group token, 'https://gitlab.com/groups/{group.group_path}/-/settings/access_tokens'.",
    "The expiry {date} must be the payload's object_attributes.expires_at (format YYYY-MM-DD) reformatted as abbreviated-month style '%b %d, %Y' (e.g. '2024-01-26' becomes 'Jan 26, 2024').",
    "The Zulip topic for the notification must be the group's group_name when the payload contains a 'group' object, and otherwise the project's name."
  ],
  "reason": "The test drives the pre-existing GitLab webhook HTTP endpoint via check_webhook and asserts only user-visible outcomes: the topic and the exact notification message (wording, link target, date format). The event header name 'Resource Access Token Hook' and payload shape are dictated by GitLab itself, not by the fix author. No internal helper names, templates, or module layout are referenced by the test \u2014 the new function names and template constant in the code diff are invisible to it. All bindings are contract surface a ticket would legitimately pin (user-facing message text, URL construction, topic rule, date format), so with these requirements in the brief the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue names the missing event category, and the expected-behavior evidence plus interface requirements pin down the exact payload shapes (project vs. group), the exact message format, URL construction for both resource types, the date reformatting, and the topic selection rule. Two engineers working independently from this brief would produce byte-identical notification messages and topics."
}
