# ZT-130cc7b9ad90 -- email_mirror: Add subject to body when truncated

- lang: py   issue: #10539   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/130cc7b9ad903f0f940a12dd88b73a300313e4f6
- f2p: zerver.tests.test_email_mirror.TestStreamEmailMessagesSubjectStripping.test_subject_added_for_every_message
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavioral bug fix / small feature",
  "reason": "Well-specified behavioral change in the email mirror: when an email subject exceeds MAX_TOPIC_NAME_LENGTH, the subject is prepended to the message body. Observable through the pre-existing process_stream_message/construct_zulip_body path, testable by feeding an email with a long subject and asserting on the resulting message content. No refactor, i18n, docs, migration, or version-gating concerns."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "The hidden test only uses interfaces that pre-exist at the base commit: `truncate_topic` (long-standing helper in zerver.lib.message), `MAX_TOPIC_NAME_LENGTH` (pre-existing constant that the fix itself merely imports, not defines), and existing email-mirror test utilities like `process_message`, `get_channel_email_token`, and `encode_email_address`. It asserts user-visible outcomes \u2014 the topic is the truncated subject and the message body contains the full subject via the pre-existing '**Subject:** ...' body format already produced by construct_zulip_body's existing subject_in_body/show_sender paths. The fix introduces no new symbols at all (it only sets an existing option flag), so the test cannot be coupled to author-chosen names."
}
