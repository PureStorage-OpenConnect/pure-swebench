# ZT-facbdf08fc2f -- integrations: Handle approval/unapproval for GitLab MRs.

- lang: py   issue: #34222   tier: B
- fix: https://github.com/zulip/zulip/commit/facbdf08fc2fe99838fc413d02c39dd1adbf16d8
- f2p: zerver.webhooks.gitlab.tests.GitlabHookTests.test_merge_request_approval_event_message, zerver.webhooks.gitlab.tests.GitlabHookTests.test_merge_request_unapproval_event_message, zerver.webhooks.gitlab.tests.GitlabHookTests.test_merge_request_updated_event_message
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real integration work: adds handling for GitLab's multi-approver 'approval'/'unapproval' merge-request webhook events plus human-readable action phrasing. The observable outcome is deterministic \u2014 posting a fixture payload to the webhook endpoint yields a specific short notification message and topic. The hidden test grades exactly that behavior (fails before: unknown event / raw action text; passes after), using fixture-driven assertions on a one-line message rather than a brittle long snapshot or incidental formatting."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The GitLab webhook integration must handle merge request events whose payload has object_attributes.action set to \"approval\" or \"unapproval\" (sent by GitLab when a merge request requires multiple approvers), instead of ignoring or erroring on them.",
    "For an \"approval\" event, the notification message must phrase the action as \"added their approval for\", e.g. \"<user> added their approval for <linked MR>\" following the existing merge-request message format.",
    "For an \"unapproval\" event, the notification message must phrase the action as \"removed their approval for\", following the same format."
  ],
  "reason": "The hidden test drives the pre-existing webhook endpoint with new GitLab fixture payloads and asserts the resulting user-visible topic and message. The topic and the overall message template ('<user> <action> [MR #N title](url)') follow conventions that already exist at the base commit, and the dispatch key ('Merge Request Hook approval') is derived mechanically from GitLab's own payload fields plus the existing event-mapper convention. The only new surface the test pins is the user-facing action wording ('added their approval for' / 'removed their approval for'), which a ticket would legitimately dictate as the notification copy. No private helper names, mock targets, or internal structures are bound; with the wording in the brief, the test grades correctness."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue names the exact sub-events to support, the evidence shows the precise payload shapes (object_attributes.action values 'approval'/'unapproval', fixture names, MR iid/title/url fields), and the interface requirements pin the exact message phrasing. Together these determine a checkable outcome: topic format, message body format, and fixture naming are all specified concretely enough for independent compatible implementations."
}
