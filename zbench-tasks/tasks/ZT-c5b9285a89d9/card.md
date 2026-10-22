# ZT-c5b9285a89d9 -- integrations: Add Redmine webhook integration.

- lang: py   issue: #35270   tier: B
- fix: https://github.com/zulip/zulip/commit/c5b9285a89d9af65d11e28c917045b3312a354e3
- f2p: zerver.webhooks.redmine.tests.RedmineHookTests.test_issue_opened, zerver.webhooks.redmine.tests.RedmineHookTests.test_issue_opened_without_assignee, zerver.webhooks.redmine.tests.RedmineHookTests.test_issue_updated
- p2p: zerver.tests.test_integrations

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature (incoming webhook integration)",
  "reason": "Real, plausibly-assigned engineering task (add a Redmine incoming webhook handler) with a deterministic hidden grader: WebhookTestCase posts fixed JSON fixtures and asserts the topic and message content the bot sends. For a webhook integration, the sent message IS the observable behavior, so asserting it is outcome-grading, not format brittleness \u2014 the expected strings are short, deterministic, and cover meaningful variants (with/without assignee, update with journal notes). Fails before the change (endpoint doesn't exist), passes after. No snapshot/API_FEATURE_LEVEL/migration/time-gating concerns."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "A new incoming webhook integration named `redmine` is registered, reachable at the standard external-webhook URL `/api/v1/external/redmine` with the usual `api_key` and `stream` query parameters (following Zulip's existing incoming-webhook framework and view-naming convention).",
    "The webhook accepts the Redmine webhook-plugin JSON envelope: a top-level `payload` object containing `action` (string, values include `opened` and `updated`), `url` (string, link to the issue), `issue` (object with integer `id`, string `subject`, string `description`, `author` object with `firstname`/`lastname`, and `assignee` which is either a user object with `firstname`/`lastname` or null), and for updates a `journal` object whose `notes` string holds the update comment.",
    "The Zulip topic for any issue event is `Issue #<id> <subject>`, e.g. `Issue #191 Found a bug`.",
    "For `action: opened`, the message is `**<author firstname> <author lastname>** opened [#<id> <subject>](<url>) for **<assignee firstname> <assignee lastname>**.` \u2014 the ` for **...**` clause is omitted entirely when `assignee` is null \u2014 followed, when a non-empty description exists, by a blank line and the description wrapped in a `~~~ quote` / `~~~` fenced block.",
    "For `action: updated`, the message is `**<author firstname> <author lastname>** updated [#<id> <subject>](<url>).` followed, when non-empty journal notes exist, by a blank line and the notes wrapped in a `~~~ quote` / `~~~` fenced block.",
    "Author and assignee display names are rendered as `<firstname> <lastname>` joined by a single space."
  ],
  "reason": "The test exercises only the public HTTP webhook endpoint via the pre-existing WebhookTestCase harness (check_webhook posts a fixture and asserts the resulting stream topic and message). It binds to no internal names from the fix \u2014 no helper functions, templates, mock targets, or module internals; the fixture payloads are supplied by the test itself and mirror Redmine's external payload format. What it does pin down is new public surface: the integration/endpoint name `redmine`, the accepted payload shape, and the exact user-facing topic and message wording (including the assignee clause, quote-fence formatting, and null-assignee behavior). All of these are product requirements a ticket would legitimately dictate; given the contract above, the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the goal (replace the Redmine plugin integration with a webhook integration and remove the old catalog entry/templates), and the expected-behavior evidence pins down the exact payload envelope, topic format, and message formats for opened (with and without assignee) and updated events, making the outcome determinate and checkable."
}
