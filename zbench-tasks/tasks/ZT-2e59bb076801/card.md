# ZT-2e59bb076801 -- empty-feed: Show special banner if muted topics in channel.

- lang: web   issue: #31601   tier: B
- fix: https://github.com/zulip/zulip/commit/2e59bb076801da91cead507227271df4c532cf8a
- f2p: web/tests/message_view.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature (UI behavior)",
  "reason": "Real, plausibly-assigned feature: show a dedicated empty-feed banner when a channel's messages are all in muted topics. The hidden test grades observable behavior deterministically \u2014 it toggles empty()/visibly_empty() and asserts which banner renders, following the exact same empty_narrow_html assertion pattern already used throughout message_view.test.cjs for every other banner. The pinned strings are the banner content itself (the deliverable specified by the issue), not incidental formatting or a snapshot, and the test also verifies the fallback banner still appears when no muted topics exist (fail-before/pass-after is clear)."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When the user narrows to a channel they are subscribed to and the message feed renders as empty even though the channel contains messages (i.e. every message is in a muted topic \u2014 determinable via the current message list's pre-existing visibly_empty() and empty() methods), the empty-narrow banner must show a muted-topics notice instead of the 'start the conversation' prompt.",
    "The muted-topics banner title is the user-facing string: \"You have muted all the topics in this channel.\"",
    "The muted-topics banner body is the user-facing HTML: \"To view a muted topic, click <b>show all topics</b> in the left sidebar, and select one from the list. Learn more\" \u2014 where 'Learn more' is a link to /help/mute-a-topic opening in a new tab (target=\"_blank\" rel=\"noopener noreferrer\").",
    "When the channel genuinely has no messages at all (the current message list is truly empty), the existing 'Why not start the conversation?' banner must still be shown, unchanged."
  ],
  "reason": "The test exercises behavior through show_empty_narrow_message, a pre-existing entry point, and drives state through pre-existing public interfaces: the message_lists module's `current` export and MessageList's visibly_empty()/empty() methods, all present at the base commit (the MessageList/MessageListData construction and MessageListView mock are standard scaffolding for those pre-existing modules, not new fix-invented surface). The only new bindings are the two user-facing banner strings and the help-link URL/attributes, which a ticket would legitimately pin verbatim, plus the visibly_empty-but-not-empty condition, which is a product requirement expressible against existing API. No private helpers, internal field names, or fix-invented module layout are referenced, so a brief containing the contract above lets the test grade correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product intent, and the expected-behavior evidence pins down the exact user-facing strings (title and body differ from the draft wording in the issue \u2014 the evidence's strings are authoritative), the link target and attributes, the visibly_empty()/empty() distinction used to detect the muted-topics case, and that the default banner is unchanged when the channel is truly empty. This is a determinate, checkable outcome."
}
