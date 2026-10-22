# ZT-59d5d29ed857 -- integrations: Add support for GitLab design comments.

- lang: py   issue: #26199   tier: B
- fix: https://github.com/zulip/zulip/commit/59d5d29ed857dabe470c0c40eaf782846ec6571a
- f2p: zerver.webhooks.gitlab.tests.GitlabHookTests.test_note_confidential_issue_event_message, zerver.webhooks.gitlab.tests.GitlabHookTests.test_note_design_event_message, zerver.webhooks.gitlab.tests.GitlabHookTests.test_note_design_with_custom_topic_in_url, zerver.webhooks.gitlab.tests.GitlabHookTests.test_note_snippet_old_event_message
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Adds GitLab design-comment event support to the webhook integration \u2014 a realistic, assignable engineering task. The hidden test uses Zulip's standard webhook fixture pattern: it posts a recorded payload and asserts the resulting topic and message. The message string IS the observable behavior of a webhook integration (topic routing, comment/design URLs, comment content), it's fully deterministic given the fixture, and the assertions are short templated strings rather than incidental snapshots. Fails before the change (unsupported event), passes after."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The GitLab webhook integration must handle note events whose object_attributes.type/noteable_type indicates a design comment (noteable_type \"DesignManagement::Design\", including the confidential variant) instead of failing as an unsupported event.",
    "For design comments, the Zulip topic must be \"{repository name} / design {design filename}\", where the design filename is the last path segment of object_attributes.position.new_path (e.g. \"testing-zulip-gitlab-integration / design Screenshot.png\").",
    "Since design-note payloads carry no direct issue field or comment URL, the design's web URL must be constructed as \"{repository homepage}/-/issues/{issue number}/designs/{design filename}\", where the issue number is parsed from the position.new_path of the form \"designs/issue-{N}/{filename}\".",
    "The comment URL must be the design URL with the anchor \"#note_{object_attributes.id}\" appended.",
    "The message body for a design comment must be \"{commenter's display name} [commented]({comment URL}) on design [{design filename}]({design URL}):\" followed by the note text rendered in the integration's standard quote block (\"~~~ quote\\n{note}\\n~~~\")."
  ],
  "reason": "The test drives the pre-existing webhook endpoint via the standard check_webhook harness and asserts only user-visible outcomes: the Zulip topic string and rendered message. It binds to no new function names, internal helpers, or mock targets \u2014 parse_design_comment, skip_previews, and the template constants in the fix are never referenced. What it does pin is new user-facing contract surface: the exact topic format, message wording, and the URL-construction rule for designs (issue number derived from new_path, #note_{id} anchor) \u2014 all things a ticket for 'support GitLab design comments' would legitimately dictate, including the sample payload shape. The custom-topic test exercises pre-existing generic behavior (topic query parameter with '[[repo](url)]' prefix). With the contract above in the brief, the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue supplies the failing scenario and a full sample payload, and the expected-behavior evidence pins down the exact topic and message strings for both the default and fixed-topic cases, including the URL-construction scheme. Together they define a determinate, checkable outcome."
}
