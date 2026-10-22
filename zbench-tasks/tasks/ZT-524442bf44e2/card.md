# ZT-524442bf44e2 -- streams-ui: Add UI to update and archive channel folders.

- lang: web   issue: #35498   tier: B
- fix: https://github.com/zulip/zulip/commit/524442bf44e2b8ce3bf04e40d764c3e32ffeca7c
- f2p: web/tests/channel_folders.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Real feature work (edit/archive channel folders UI) that someone would plausibly be assigned. The hidden test grades observable behavior deterministically: it exercises the new channel_folders.get_stream_ids_in_folder() helper with concrete stream/folder fixtures and asserts the returned stream-id arrays. No snapshot pinning, no exact-string/HTML assertions, no version or time gating \u2014 the test fails before the change (function doesn't exist) and passes after, based on data behavior rather than incidental formatting."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The `channel_folders` web module (web/src/channel_folders.ts) gains an exported function `get_stream_ids_in_folder(folder_id: number): number[]`, intended as the cross-module API for other frontend components (e.g. stream settings) to look up a folder's channels.",
    "`get_stream_ids_in_folder` returns the `stream_id` of every known/registered stream whose `folder_id` equals the given folder ID; streams with a different `folder_id` or with `folder_id` null are excluded.",
    "`get_stream_ids_in_folder` returns an empty array (not null/undefined) when no streams belong to the folder.",
    "The returned stream IDs appear in the order the streams were registered in the client's stream data store (i.e. unsorted insertion order, no additional sorting applied)."
  ],
  "reason": "The test exercises only one new binding: `channel_folders.get_stream_ids_in_folder`. Everything else it touches already exists at base (`zrequire`, `make_stream`, `stream_data.add_sub`, the `folder_id` field on subscriptions, and existing channel_folders APIs like `get_channel_folder_by_id`). The new function is a data-layer query exported for use by other modules (the fix calls it from stream_settings_components), which is exactly the kind of public-API surface a ticket would legitimately dictate \u2014 name, argument, return shape, empty-array semantics, and ordering. The test does not stub internals, does not depend on `stream_settings_components` private helpers, and does not encode any implementation choice (e.g. how filtering is done). With the contract items above in the brief, the test grades correctness rather than name-guessing, so this is specifiable, not coupled."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue specifies the UI (hover edit/delete buttons, tooltips, and exact modal titles/copy/buttons), and the interface requirements pin down the exported channel_folders API precisely enough (name, signature, filtering semantics, empty-array behavior, insertion ordering) that two independent implementations would be compatible and checkable."
}
