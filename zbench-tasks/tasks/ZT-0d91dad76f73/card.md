# ZT-0d91dad76f73 -- pm_list: Hide conversations with deactivated users by default.

- lang: web   issue: #35102   tier: B
- fix: https://github.com/zulip/zulip/commit/0d91dad76f737dee6fc8eaaf13ab8f8affc0e99e
- f2p: web/tests/pm_list_data.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix / behavior change (UI logic)",
  "reason": "Real, plausibly-assigned change with observable behavior: unzoomed DM list excludes conversations containing deactivated users while zoomed view shows all, and the more-conversations unread count absorbs hidden ones. The hidden test grades this outcome deterministically via recipient lists, counts, and unread totals in pm_list_data's pure data layer \u2014 it would fail before the change and pass after. The assertions enumerate expected conversation names, but that is the behavior under test (which conversations appear and in what order), not an incidental format snapshot; no exact-string/HTML pinning, no time/version gating."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The direct-message list's per-conversation display object renames its boolean field `is_deactivated` to `includes_deactivated_user`, which is true when ANY participant in the conversation (not just the first/only user) is a deactivated account; consumers of `pm_list_data.get_conversations()` read this field.",
    "In the unzoomed (collapsed) direct-message list, conversations that include any deactivated user are excluded from `conversations_to_be_shown`; unread messages in those excluded conversations are added to `more_conversations_unread_count`.",
    "In the zoomed (expanded) direct-message list, all conversations are shown, including those with deactivated users, and `more_conversations_unread_count` is 0.",
    "The unzoomed cap of 8 most-recent conversations (`max_conversations_to_show`) is applied after excluding deactivated-user conversations, i.e. up to 8 of the remaining eligible conversations are shown rather than 8 slots being consumed by filtered-out entries."
  ],
  "reason": "Almost everything the new test asserts flows through interfaces that exist at the base commit: `pm_list_data.get_list_info()` and its `conversations_to_be_shown` / `more_conversations_unread_count` return shape, `pm_conversations.recent.insert`, `people.deactivate` / `people.add_active_user`, and recipient display strings. The only new binding is the renamed display-object field `includes_deactivated_user` replacing the pre-existing `is_deactivated`. That field is part of the module's exported `DisplayObject` output consumed by the rendering layer, and a ticket about correctly hiding group DMs containing deactivated users would legitimately dictate both the rename (the old name's single-user semantics were the bug) and the filtering/zoom/unread-count semantics. Given these requirements in a brief, the test grades behavioral correctness, not name-guessing; internal choices like the `should_show_conversation` refactor and count-based (vs index-based) capping are not directly bound, only their observable effects."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product intent (hide DMs with any deactivated participant in the default view, show them when expanded, for both 1:1 and group DMs), and the evidence plus interface requirements pin down the exact observable contract: the renamed includes_deactivated_user field and its any-participant semantics, exclusion from conversations_to_be_shown when unzoomed, unreads from hidden conversations rolling into more_conversations_unread_count, full visibility and zero more-count when zoomed, and cap-after-filter ordering. This is determinate and checkable by two independent engineers."
}
