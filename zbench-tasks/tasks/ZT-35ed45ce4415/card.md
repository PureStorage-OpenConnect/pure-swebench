# ZT-35ed45ce4415 -- import: Send Welcome Bot messages to users from non-Zulip exports.

- lang: py   issue: #34820   tier: B
- fix: https://github.com/zulip/zulip/commit/35ed45ce44155eb7b339d04b4ad088429924fa6a
- f2p: zerver.tests.test_mattermost_importer.MatterMostImporter.test_do_convert_data_with_direct_messages, zerver.tests.test_rocketchat_importer.RocketChatImporter.test_do_convert_data, zerver.tests.test_slack_importer.SlackImporter.test_slack_import_to_existing_database
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real engineering task: after importing a realm from a non-Zulip export (Slack/Mattermost/Rocket.Chat), send Welcome Bot onboarding DMs to each imported active human user. The hidden tests grade observable behavior deterministically \u2014 message counts and distinct personal-message recipients in the imported realm increase by the expected amounts across three importer test suites (fail-before/pass-after). Assertions are on counts and stable properties (sender email, recipient sets), not exact rendered output of the new Welcome Bot messages, so the grader is not brittle format-pinning."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test diff touches no new identifiers at all \u2014 it only updates expected message counts in pre-existing importer tests, asserted through interfaces that exist at the base commit (Message.objects queries, Recipient types, ZulipTestCase helpers). The count deltas follow deterministically from the required behavior: after a third-party (non-Zulip) import, each active human user receives the standard Welcome Bot initial direct message via the pre-existing zerver.lib.onboarding.send_initial_direct_message flow (e.g., Mattermost: +3 messages for 3 human users, personal recipient sets grow by one Welcome Bot conversation per user). The new helper the fix introduces (send_zulip_initial_messages_after_import) is never referenced by the tests, so no internal naming or structure is coupled. A solver told only the task requirement \u2014 'send the standard onboarding welcome messages to imported users when the export came from another product' \u2014 would produce exactly these observable counts; the test grades behavior, not name-guessing."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_mattermost_importer.MatterMostImporter.test_do_convert_data_with_direct_messages",
    "zerver.tests.test_rocketchat_importer.RocketChatImporter.test_do_convert_data",
    "zerver.tests.test_slack_importer.SlackImporter.test_slack_import_to_existing_database"
  ],
  "reason": "The diff matches Zulip commit 35ed45ce44 ('import: Send Welcome Bot messages to users from non-Zulip exports'). Mapping each hunk's line numbers onto that revision: both mattermost hunks (lines 877, 911) fall inside MatterMostImporter.test_do_convert_data_with_direct_messages (defined at line 785, next method at 923); both rocketchat hunks (1030, 1071) fall inside RocketChatImporter.test_do_convert_data (defined at 894); and the slack hunk (1812) falls inside SlackImporter.test_slack_import_to_existing_database. Only assertion counts inside these three existing methods were modified \u2014 no new tests were added."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user-visible problem (empty Welcome Bot conversation for imported accounts) and the desired outcome (same onboarding messages as a normal new user). The evidence confirms the change is in the shared import path \u2014 message counts rise across Slack, Mattermost, and Rocket.Chat imports by one onboarding DM set per imported human user, delivered as personal messages to per-user recipients. This is enough to specify a determinate, checkable behavior without revealing test details."
}
