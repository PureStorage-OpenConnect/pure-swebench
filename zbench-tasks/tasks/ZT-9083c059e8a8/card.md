# ZT-9083c059e8a8 -- stream_type_icon: Render stream privacy icons in message references.

- lang: web   issue: #19058   tier: B
- fix: https://github.com/zulip/zulip/commit/9083c059e8a8919ce982742c5faeb98b23d5cb74
- f2p: web/tests/rendered_markdown.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, plausibly-assigned UI feature (render stream privacy icons in message stream/topic references) with a clear fail-before/pass-after signal: the hidden test verifies that update_elements now renders via the decorated_channel_name template and passes the full sub object (including invite_only/is_web_public/is_archived) into topic_link context. The test grades observable data-flow behavior through mocked templates rather than pinning rendered HTML snapshots or exact long strings; the deepEqual on topic_link context is a small, deterministic data contract, not incidental formatting. Deterministic node-based web test, no time/version gating."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "Stream links (`a.stream` elements) in rendered message content must be re-rendered by calling the pre-existing shared template `web/templates/decorated_channel_name.hbs` (which renders the channel name with its privacy/archived icon), passing the channel's sub object (from sub_store) under the template's existing `stream` parameter; the sub carries the existing fields stream_id, name, invite_only, is_web_public, is_archived.",
    "The `topic_link.hbs` template context gains a new field `stream`: the full sub object for the linked channel (so the template can render the decorated channel name via the decorated_channel_name partial). The existing context fields (channel_id, channel_name, topic_display_name, is_empty_string_topic, href) are unchanged and no other new fields are added (the test deepEquals the exact context).",
    "Stream/topic links whose channel is private (invite_only), web-public, or archived must still go through the same decorated_channel_name render path with the corresponding sub flags intact (the decoration reflects the channel's privacy/archived state)."
  ],
  "reason": "The test verifies behavior by mocking Handlebars templates \u2014 Zulip's standard component-layer test idiom. `decorated_channel_name.hbs` and its `stream` parameter pre-exist at base (the fix imports, not creates, it), so binding to it is reuse of existing public surface; the only genuinely new name is the `stream` field added to the pre-existing `topic_link.hbs` context, which a design brief would legitimately dictate ('pass the full sub object so the partial can render the privacy icon'). No private helper names, internal call signatures, or invented module layout are asserted, so a brief containing the listed contract makes the test grade correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user-visible goal (channel type icons in rendered message channel names), and the expected-behavior evidence plus interface requirements pin down the exact mechanism: a.stream anchors re-rendered via decorated_channel_name.hbs with the sub object as `stream`, and topic_link.hbs gaining exactly one new context field `stream` while keeping the existing fields unchanged. That is determinate and checkable, and covers private, web-public, and archived channels."
}
