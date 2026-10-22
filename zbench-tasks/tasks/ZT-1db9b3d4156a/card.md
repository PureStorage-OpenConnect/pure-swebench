# ZT-1db9b3d4156a -- settings: Show privacy icons in 'Add default channels' dropdown.

- lang: web   issue: #38202   tier: B
- fix: https://github.com/zulip/zulip/commit/1db9b3d4156ae7bd543ca16a75c315887910dc61
- f2p: web/tests/stream_data.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real UI feature (privacy icons in the default-channel dropdown) backed by an observable data-layer change: the options function now returns the full StreamSubscription alongside name/id. The hidden node test deterministically asserts the new return shape on a small fixture \u2014 it fails before the change and passes after, with no snapshot pinning, rendering dependence, or nondeterminism. The rename is incidental to a genuine behavior change, not a pure rename."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "the `stream_data` module must export a function `get_default_stream_options()` (replacing the former `get_non_default_stream_names()`) that returns the streams eligible to be added as default streams: all streams that are not already default, not private (invite_only), and not archived",
    "each element of the array returned by `get_default_stream_options()` is an object with three fields: `name` (string, the stream's name), `unique_id` (number, the stream's stream_id), and `stream` (the full StreamSubscription object for that stream), so callers such as the default-streams settings UI can access complete stream data for each option"
  ],
  "reason": "The test binds to a new exported function name on the stream_data module and to its return shape. stream_data's exports are the module's public API consumed by other frontend modules (settings_streams), and both the function name and the exact return-object fields (`name`, `unique_id`, `stream`) are surface a ticket/design brief could legitimately dictate ('expose full stream objects to the default-stream picker via get_default_stream_options'). Given those requirements in the brief, the test grades behavioral correctness (correct filtering of default/private/archived streams and correct field values), not name-guessing. No private helpers, mock targets, or internal data structures are referenced \u2014 the assertion goes through the exported interface only."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user-visible goal (privacy icons in the add-default-channel dropdown), and the evidence plus interface requirements pin down the exact data-layer contract: a renamed function `get_default_stream_options()` returning {name, unique_id, stream} with unchanged eligibility filtering. Together these give a determinate, checkable outcome."
}
