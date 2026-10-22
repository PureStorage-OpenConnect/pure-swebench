# ZT-3d9bf39f8ec0 -- webhooks/github: Add silent mention support for GitHub usernames.

- lang: py   issue: #34078   tier: B
- fix: https://github.com/zulip/zulip/commit/3d9bf39f8ec063aca56a08f97de71abc009af066
- f2p: zerver.webhooks.github.tests.GitHubWebhookTest.test_issue_comment_silent_mention, zerver.webhooks.github.tests.GitHubWebhookTest.test_issue_comment_silent_mention_with_multiple_matches
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Real, plausibly-assigned feature work: the GitHub webhook learns to map GitHub usernames to Zulip users via the GitHub custom profile field and emit silent mentions. The hidden tests grade observable outcome deterministically \u2014 they set up a user's GitHub username profile field, replay a fixture, and assert the resulting webhook message, including the fallback to the plain username when multiple users match. While the tests do compare full message strings, that is the standard Zulip WebhookTestCase pattern and the message content (silent-mention syntax vs. plain name) is precisely the behavior the change introduces; the strings are short, deterministic, and fail-before/pass-after. Not format-over-behavior brittleness."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When a GitHub webhook message displays a sender's GitHub login, and exactly one user in the realm has the 'GitHub username' custom profile field (the pre-existing default github external-account field) set to that login, the sender name is replaced by a silent mention of that Zulip user",
    "The silent mention must use Zulip's canonical `@_**{full_name}|{user_id}**` form (i.e., the output of the pre-existing silent_mention_syntax_for_user helper), not the bare `@_**name**` variant",
    "If multiple users in the realm have that field set to the same GitHub login (ambiguous match), fall back to displaying the plain GitHub login unchanged",
    "The rest of the message (action link, issue link, quoted comment body, topic) keeps the existing issue_comment format byte-for-byte"
  ],
  "reason": "The test invokes only interfaces that pre-exist at the base commit \u2014 verified against upstream parent a82d7b8476e4: set_user_custom_profile_data (test_classes.py:2389), guess_zulip_user_from_external_account (webhooks/common.py:348, and the test doesn't reference it anyway), and the populate_db-provisioned 'GitHub username' field. No private helper names, mock targets, or internal structures are bound. The test asserts new user-visible message content whose semantics (match source, exact @_**name|id** mention form, multiple-match fallback to plain login) are legitimate spec surface; with those stated in the brief, the test grades behavior rather than author-specific choices."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the feature intent (silent mentions via the GitHub username profile field, with a generic unique-match helper), and the expected-behavior evidence pins down the exact observable outcomes: the canonical silent-mention syntax with user ID, the ambiguous-match fallback to the plain login, and that the rest of the issue_comment message format is unchanged. Together these give a determinate, checkable specification."
}
