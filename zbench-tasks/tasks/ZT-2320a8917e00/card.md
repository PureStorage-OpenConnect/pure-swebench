# ZT-2320a8917e00 -- channels: Include unsubscribed channels in move selectors.

- lang: web   issue: #33670   tier: B
- fix: https://github.com/zulip/zulip/commit/2320a8917e00b921870fd166005ed096efa7552a
- f2p: web/tests/stream_data.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, plausibly-assigned frontend feature: move-topic/message channel selectors should also list unsubscribed channels the user can access, with subscribed channels sorted first. The change is behavioral and observable through a new pure function (get_streams_for_move_messages_widget) whose output \u2014 which streams are included and their ordering \u2014 the hidden test grades deterministically. The test's assert.deepEqual comparisons look verbose but are not snapshot brittleness: they compare against the exact stream objects the test itself constructs and passes in, matching the established pattern already used for get_options_for_dropdown_widget in the same test file. There is no non-deterministic or incidental formatting involved; the assertions fail before the fix (unsubscribed streams absent) and pass after, which is exactly the fail-before/pass-after signal we want."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The `stream_data` module gains an exported function `get_streams_for_move_messages_widget()` (public within the web app; consumed by the move-topic/move-messages popover) that returns the channel list for the move-messages destination dropdown.",
    "Each returned entry is a dropdown-widget option of the pre-existing shape `{name, unique_id, stream}`: `name` is the channel's name, `unique_id` is its `stream_id`, and `stream` is the channel's full subscription object, unmodified.",
    "The returned list includes every non-archived channel whose content the user can access \u2014 not just subscribed channels; unsubscribed channels are included when the user has content access (e.g. public channels, or private channels the user can subscribe to per the channel's group-based permission settings such as `can_subscribe_group`), and excluded when access is lost.",
    "Ordering: subscribed channels come before unsubscribed channels; within each group, channels are sorted alphabetically by name, case-insensitively."
  ],
  "reason": "The test binds to one new name, `stream_data.get_streams_for_move_messages_widget`, an exported module function intended as the API for the move-messages dropdown \u2014 exactly the kind of surface a ticket would dictate. Its asserted return shape reuses the pre-existing `dropdown_widget.Option`+`stream` convention already used by `get_options_for_dropdown_widget` at the base commit, and everything else the test checks is behavioral: which channels appear (archived excluded, content-access included, reacting to `can_subscribe_group` changes) and their ordering (subscribed-first, then case-insensitive alphabetical). The `can_*_group` fields added to test fixtures are pre-existing server API fields consumed by existing access-check helpers, not new contract. No private helpers, mocks of internals, or invented internal structure are referenced, so a brief stating the contract above lets the test grade correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product goal (include all content-accessible channels, unsubscribed below subscribed, like the mention typeahead), the evidence pins down the observable contract (a stream_data function returning {name, unique_id, stream} options, inclusion/exclusion driven by archived status and content access including can_subscribe_group-based access for private channels, and re-evaluation as channel state changes), and the interface requirements fix the exact export name, option shape, inclusion rule, and ordering. Together these are determinate and checkable by two independent engineers."
}
