# ZT-ecdfb14cb7b9 -- message-view: Fix banner/bookend for private channel no content access.

- lang: web   issue: #36075   tier: B
- fix: https://github.com/zulip/zulip/commit/ecdfb14cb7b9ea0d54be57432abfcff995f04416
- f2p: web/tests/message_list.test.cjs, web/tests/message_view.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix (UI behavior)",
  "reason": "Real, plausibly-assigned fix: when a user has metadata access but no content access to a private channel, the empty-narrow banner should say access is denied and no trailing subscribe bookend should render. The hidden tests grade observable behavior deterministically: one asserts render_trailing_bookend is not called (num_calls === 0) when can_toggle_subscription is false, the other asserts the specific banner message shown for the private-channel case. The string assertion is a short, single banner title introduced by the change (via the mocked-translation harness, so deterministic), not a long snapshot or incidental-format pin \u2014 this is the standard way Zulip's node tests verify which banner is chosen. Fails before the fix, passes after; not format-brittle."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When narrowing to a private channel (invite_only) that the user is not subscribed to and is not allowed to subscribe to, the empty-narrow banner must show the user-facing message: 'You are not allowed to view messages in this private channel.' (marked for translation, title only, no extra HTML).",
    "Whether the user is allowed to subscribe must be determined via the pre-existing exported helper stream_data.can_toggle_subscription(sub); code deciding subscribe-related UI for a channel must route through this function rather than reimplementing the permission check.",
    "When the user is not subscribed to the narrowed channel and can_toggle_subscription returns false, the message list must not render any trailing bookend (the subscribe/unsubscribe bookend rendering is skipped entirely)."
  ],
  "reason": "The bookend test exercises pre-existing interfaces (update_trailing_bookend, render_trailing_bookend) and stubs stream_data.can_toggle_subscription \u2014 an exported, pre-existing public API already used at the base commit (narrow_banner calls it) as the canonical 'can this user subscribe' check, so requiring the fix to consult it is a legitimate spec-level directive, not a private-helper guess. The other stub targets (is_subscribed, get_sub_by_id, settings_data.user_has_permission_for_group_setting) are likewise pre-existing module APIs already mocked in these test files at base. The only genuinely new surface the test binds to is the user-facing banner string for private channels without content access, which a ticket would routinely pin verbatim. No new internal names, data-structure fields, or module layout invented by the fix are referenced; with the three contract items in the brief, the test grades behavior rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the desired UX (no bookend, specific placeholder text) and the evidence plus interface requirements pin down the exact conditions (invite_only, unsubscribed, can_toggle_subscription false), the exact message string, the title-only rendering, and that the bookend render must be skipped entirely \u2014 enough for two engineers to build compatible implementations."
}
