# ZT-24291574985f -- streams: Don't glue translated strings in new channel notification.

- lang: py   issue: #30212   tier: B
- fix: https://github.com/zulip/zulip/commit/24291574985fd35791587773f593539ed8f707a1
- f2p: zerver.tests.test_subs.TestCreateStreams.test_channel_create_message_exists_for_all_policy_types
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real i18n bug fix with behavior change (notification message construction per channel policy, not translation string churn). The hidden test grades observable outcome deterministically: it creates a channel for each permission policy via the API and asserts the notification message exists (or is absent for public_protected_history) and contains a short policy-label substring via assertIn. It does not pin an exact full message, snapshot, or formatting \u2014 fail-before/pass-after is clean and robust."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When a channel is created, the notification message posted to the channel's \"channel events\" topic must state the channel's permission type in bold at the start of the message, using these exact labels per policy: \"**Web-public**\" for web_public channels, \"**Public**\" for public channels, \"**Private, shared history**\" for private channels with shared history, and \"**Private, protected history**\" for private channels with protected history (e.g. \"**Public** channel created by {user}. **Description:** ...\").",
    "Exactly one channel-creation notification message is posted to the \"channel events\" topic for each newly created channel of the above four policy types.",
    "Channels created with the Zephyr-realm-only \"public_protected_history\" permission policy must not receive any channel-creation notification message (zero messages in the \"channel events\" topic)."
  ],
  "reason": "The test drives creation through the pre-existing subscriptions API and iterates the pre-existing Stream.PERMISSION_POLICIES keys; the only new surface it binds to is the user-facing wording of the channel-creation notification (bold policy labels) and the product rule that public_protected_history channels get no notification. Both are requirements a ticket would legitimately dictate \u2014 especially since the fix's purpose is replacing an interpolated template with fixed translatable sentences \u2014 so a solver handed this contract would be graded on correctness, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives a clear reproduction of the mixed-locale bug, and the expected-behavior evidence plus interface requirements pin down the exact message format (bold policy labels per PERMISSION_POLICIES entry), the one-message-per-channel invariant, and the Zephyr public_protected_history exception, making the outcome determinate and checkable."
}
