# ZT-ae6e58a2a401 -- message_send: Return `message_url` and `message_link` in send response.

- lang: py   issue: #15327   tier: B
- fix: https://github.com/zulip/zulip/commit/ae6e58a2a40144feb6eff7452bf438526b6f03c5
- f2p: zerver.tests.test_message_send.MessagePOSTTest.test_message_url_in_api_response, zerver.tests.test_message_send.MessagePOSTTest.test_personal_message, zerver.tests.test_message_send.PersonalMessageSendTest.test_personal_message
- p2p: zerver.tests.test_url_encoding

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, high-priority API feature (issue-backed): add message_url/message_link to the POST /messages send response. The hidden test grades observable outcomes deterministically \u2014 exact URL/link strings are the deliverable itself (URLs are the feature's output, not incidental formatting), and it covers meaningful behavior variants: metadata-access-gated channel-name inclusion, DM links, write-only bots getting ID-only URLs, group-based access, and long-term-idle subscribers. Fixture data (stream names, user IDs, testserver host) makes assertions deterministic. The assert_database_query_count(20) check is the only mildly rigid bit, but it encodes a stated requirement (no additional query) rather than incidental format, and is standard Zulip test practice. Fail-before/pass-after is clear since the response keys don't exist pre-change."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The POST /api/v1/messages API response gains a string field `message_url`: the absolute permanent URL (near-narrow link) of the sent message, e.g. https://<realm>/#narrow/channel/<id>-<name>/topic/<encoded-topic>/near/<message-id> for channel messages and https://<realm>/#narrow/dm/<comma-joined-sorted-user-ids>/near/<message-id> for direct messages.",
    "The POST /api/v1/messages API response gains a string field `message_link`: a Markdown link matching the web app's 'Copy link to message' format, `[#<channel name> > <topic> @ \ud83d\udcac](<message_url>)`, embedding the same absolute URL as `message_url`.",
    "For direct messages, which have no channel name and no standard label, `message_link` is simply equal to `message_url` (the bare URL).",
    "If the sender lacks metadata access to the channel (e.g. a non-subscribed write-only bot posting to a private channel via its owner's subscription), `message_url` must omit the channel name and use the ID-only narrow form `/#narrow/channel/<id>/topic/...`, so the channel name is not leaked; in that case `message_link` is also just the bare URL.",
    "A sender who is directly subscribed to the channel has metadata access and gets the channel name in the URL and the full Markdown `message_link`; this must hold even for long-term-idle subscribers (the subscription confirmed while authorizing the send suffices, independent of recipient-row computation).",
    "A sender whose channel access derives solely from a group-based permission (e.g. membership in the channel's can_subscribe_group), without a direct subscription, also has metadata access and gets the channel name in the URL and the full Markdown link; metadata access is resolved from the recursive group memberships already loaded to authorize the send.",
    "Resolving the sender's metadata access must not add any database queries to the send path: when the sender's group memberships were not loaded during send authorization (e.g. a bot posting via its owner's subscription), they are treated as empty rather than fetched, conservatively omitting the channel name. (The full private-channel bot send completes in the same total query count as the baseline send path, asserted as an exact query budget.)"
  ],
  "reason": "The test exercises the feature entirely through the public POST /api/v1/messages endpoint using pre-existing test infrastructure (api_post, make_stream, subscribe, check_add_user_group, do_change_stream_group_based_setting, flush_per_request_caches \u2014 all present at base). It binds to two new API response fields (`message_url`, `message_link`), exact URL/Markdown formats that follow Zulip's established narrow-URL and 'Copy link to message' conventions, and behavioral rules about when the channel name appears \u2014 all of which a ticket would legitimately dictate as API contract and privacy/product requirements. It does not mock internals or reference any new private helper names (get_message_url_and_link, sender_has_channel_metadata_access, etc. never appear in the test). The only implementation-flavored assertion is the exact database query count, but its substance \u2014 'metadata access resolution must add no queries; unloaded group memberships are treated as empty' \u2014 is a specifiable performance/behavior requirement, and a solver meeting it lands on the baseline count. Given these contract items in the brief, the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the two fields and their intent, and the expected-behavior evidence pins down every observable detail: exact URL formats for channel and DM messages, the Markdown link format with the \ud83d\udcac emoji, the metadata-access rules for subscribed, group-access, long-term-idle, and write-only-bot senders, the ID-only fallback that avoids leaking private channel names, and the no-extra-queries constraint. Together these give a determinate, independently checkable specification."
}
