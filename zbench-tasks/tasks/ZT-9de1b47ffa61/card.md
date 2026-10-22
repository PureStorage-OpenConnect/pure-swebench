# ZT-9de1b47ffa61 -- slack_import: Improve topic name for Slack threads.

- lang: py   issue: #27661   tier: B
- fix: https://github.com/zulip/zulip/commit/9de1b47ffa61a5d992ddce75fd453e7ecfe78233
- f2p: zerver.tests.test_slack_importer.SlackImporter.test_channel_message_to_zerver_message
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature/behavior-change",
  "reason": "Real engineering task: changes Slack-import thread topic naming from generic counters to date + message snippet with collision counters and truncation. The behavior is deterministically observable in the importer's output, and the hidden test asserts exactly that \u2014 the generated topic names, truncation length, collision numbering, and thread grouping. The asserted strings are short and are the spec'd output format itself, not an incidental snapshot, so the test grades behavior rather than formatting noise. Fails before, passes after."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When importing Slack threads, each thread's Zulip topic name becomes the thread's root-message date (UTC, formatted YYYY-MM-DD) followed by a space and a snippet of the thread's root message text, e.g. \"2015-06-12 message body text\" (replacing the old \"<date> Slack thread <N>\" scheme).",
    "The generated topic name is truncated to the maximum Zulip topic length (60 characters), using the single ellipsis character \"\u2026\" as the truncation marker; a topic at the limit must use the full 60 characters.",
    "When two or more distinct threads would produce the same topic name (same date and same snippet), later threads get a disambiguating numeric suffix \" (N)\" (second occurrence \" (2)\", etc.); the snippet is shortened as needed so the name including the suffix still fits within the 60-character limit.",
    "All messages belonging to one Slack thread (root message and replies sharing its thread_ts, including replies carrying Slack's parent_user_id field) are placed under that thread's single generated topic name.",
    "Thread topic snippets are taken from the raw message text as imported; importer output for threaded messages with file attachments must still record the uploads/attachments as for non-threaded messages."
  ],
  "reason": "The test drives everything through the pre-existing importer entry point (channel_message_to_zerver_message via realistic Slack export fixtures) and inspects pre-existing output structures (zerver_message rows, EXPORT_TOPIC_NAME, uploads/attachments lists). It does not import or stub the new internal helpers (get_zulip_thread_topic_name, get_parent_user_id_from_thread_message) or the thread_map/thread_counter internals. What it does pin is the exact user-visible topic-naming format: date prefix, message snippet, \"\u2026\" truncation at the 60-char topic limit, and \" (N)\" collision suffixes. Those exact strings are new behavior a solver could not derive from the base commit, but they are precisely the kind of user-facing formatting a ticket would dictate; with the contract above, the test grades correctness rather than name-guessing."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_slack_importer.SlackImporter.test_channel_message_to_zerver_message"
  ],
  "reason": "All hunks in the diff fall inside a single existing test method in zerver/tests/test_slack_importer.py within the SlackImporter test class: the fixture data (user_data, the threaded message list) and assertions (zerver_message thread topic names, uploads/attachment counts) belong to test_channel_message_to_zerver_message, which exercises channel_message_to_zerver_message's Slack-thread-to-topic conversion. No new test methods are added; the diff only extends this one method's fixtures and assertions to cover snippet-based thread topic names, truncation, and collisions."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue plus the expected-behavior evidence pin down a determinate, checkable outcome: exact name format (UTC YYYY-MM-DD + space + raw-text snippet), exact truncation rule (60-char cap, U+2026 ellipsis, full 60 chars used, with a concrete worked example), collision suffix semantics (first unchanged, second gets ' (2)', snippet re-shortened to fit), thread-grouping rules including parent_user_id replies, and attachment handling. Two engineers following this brief would produce byte-identical topic names for the same input."
}
