# ZT-0dfb70915262 -- slack_data_import: Support converting integration bot messages.

- lang: py   issue: #31162   tier: B
- fix: https://github.com/zulip/zulip/commit/0dfb70915262cec91030368e53b7472a0ef3dfe4
- f2p: zerver.tests.test_slack_importer.SlackImporter.test_channel_message_to_zerver_message_with_integration_bots
- p2p: zerver.tests.test_slack_message_conversion

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, plausibly-assigned feature: the Slack import tool learns to convert integration bot messages (blocks/attachments) and attribute them via bot_id. The hidden test feeds fixture Slack messages through channel_message_to_zerver_message and asserts the converted Zulip markdown content and sender IDs. Although it compares exact strings, the exact markdown output IS the observable behavior of a converter function \u2014 deterministic input-to-output mapping, not an incidental snapshot of unrelated formatting. It fails before the change (bot messages had empty text and no sender) and passes after, grading outcome deterministically."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test binds to no new names at all. Its only entry point is `channel_message_to_zerver_message`, a function that already exists at the base commit (the preceding test in the same file calls it with the identical signature, including `convert_slack_threads`), and its only mock target is `zerver.data_import.slack.build_usermessages`, which is likewise pre-existing and already mocked by the sibling test above. The code diff's new internal helper `process_slack_block_and_attachment` is never referenced by the test \u2014 the test exercises it purely through the public converter's output. The assertions are on user-visible import outcomes: the rendered markdown content of each imported message and the sender id. The exact expected markdown is not author-private knowledge either: each test message carries a single attachment, so the expected strings are exactly the output of the pre-existing `render_attachment`/`render_block` functions in `zerver/data_import/slack_message_conversion.py` (the diff modifies them in place, proving they exist at base, and the test docstring notes the rendering logic is already covered by slack_incoming tests). The new `\\n`-join-of-stripped-pieces assembly choice is never actually discriminated by the test, since no message produces multiple top-level pieces. Sender attribution via `bot_id` is a user-visible outcome (bot messages attributed to the bot user), not an internal name. A solver who wires the existing renderers into the import path reproduces these strings deterministically, so the test grades correctness, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the goal, the relevant functions (get_message_sending_user, fetch_shared_channel_users, the bots.info API, moving render_attachment/render_block into slack_message_conversion.py), and sample bot-message data; the evidence pins down exact observable outcomes (bot_id-based sender mapping and exact Markdown rendering for legacy attachments and Block Kit blocks). Together these determine a concrete, checkable outcome."
}
