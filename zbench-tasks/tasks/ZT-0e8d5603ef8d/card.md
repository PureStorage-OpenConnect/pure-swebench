# ZT-0e8d5603ef8d -- stream: Use can_create_topic_group setting while sending message.

- lang: web   issue: #19642   tier: B
- fix: https://github.com/zulip/zulip/commit/0e8d5603ef8d8f47412f01359bc014dac07f73d0
- f2p: web/tests/compose_actions.test.cjs, web/tests/compose_validate.test.cjs, web/tests/composebox_typeahead.test.cjs, web/tests/stream_data.test.cjs, web/tests/stream_list.test.cjs
- p2p: web/tests/message_edit.test.cjs, web/tests/compose.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Real, plausibly-assigned feature: a per-channel permission setting (can_create_topic_group) that gates creating new topics, enforced in compose validation, topic typeahead sorting, and permission checks. The hidden tests grade observable behavior deterministically \u2014 can_create_new_topics_in_stream returns true/false across role/group/spectator/archived cases, the typeahead sorter includes or omits the raw query based on permission, and compose validation blocks sends to nonexistent topics. Assertions are small, targeted deepEquals and booleans, not pinned long strings or HTML/JSON snapshots, so the test fails before and passes after on outcome rather than formatting."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "Channel (stream) objects gain a new server-provided permission field `can_create_topic_group`: the id of a user group (system or user-defined) whose members are allowed to start new topics in that channel.",
    "The server's supported permission settings for channels include an entry `can_create_topic_group` with configuration: require_system_group true, allow_internet_group false, allow_nobody_group true, allow_everyone_group true, default group `role:everyone`, no restricted list of allowed system groups.",
    "The `stream_data` module exposes a new permission-check function `can_create_new_topics_in_stream(stream_id)` returning a boolean: true iff the current user is a member (directly or via subgroups) of the channel's `can_create_topic_group`; guests are allowed when they are members of that group; it always returns false for spectators (logged-out viewers) and for archived channels.",
    "In the compose box topic typeahead, when the current user lacks permission to create new topics in the selected channel, the typed query must NOT be offered as a synthetic 'new topic' suggestion at the top of the suggestion list; when the user does have permission, the existing behavior of prepending the query (when it matches no existing topic exactly) is preserved."
  ],
  "reason": "The test binds only to new names that a ticket would legitimately dictate: the channel API field `can_create_topic_group` (mirroring existing sibling fields like `can_send_message_group`), its entry in the server-supported permission-settings metadata (server API contract, including defaults and allow_* flags the test fixtures encode), and the exported `stream_data.can_create_new_topics_in_stream(stream_id)` function, which is the module's public permission-check surface directly parallel to the pre-existing `can_post_messages_in_stream` (the test's override_rewire of it mirrors the existing rewire of that sibling function at the same call site, so it is contract surface, not an invented internal). The remaining assertions (typeahead sorter no longer suggesting the raw query without permission, group/spectator/archived semantics) check user-visible behavior through pre-existing hooks. Handed these requirements in a brief, a solver would be graded on correctness, not name-guessing; no private helpers, internal data structures, or implementation-specific mock targets are pinned."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives a full product spec (label, placement, defaults, tooltips, UI behavior, semantics), and the evidence plus interface requirements pin down the exact field name, permission-settings configuration, the stream_data function name and edge-case semantics (guests, spectators, archived channels), and the typeahead sorter behavior. Together these determine a checkable, unambiguous outcome."
}
