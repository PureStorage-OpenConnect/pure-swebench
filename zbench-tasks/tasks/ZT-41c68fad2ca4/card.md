# ZT-41c68fad2ca4 -- stream: Allow non-admins to create channel without subscribing to it.

- lang: web   issue: #33125   tier: B
- fix: https://github.com/zulip/zulip/commit/41c68fad2ca457ab5659aed6276567ab3933c9c0
- f2p: web/tests/stream_create_subscribers_data.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior-change (permissions/UX: allow non-admins to create channel without self-subscribing)",
  "reason": "Real, plausibly-assigned workflow with an observable behavior change: sync_user_ids previously force-re-added the current user, and the hidden test now asserts sorted_user_ids equals exactly [test_user101, test_user102] after syncing \u2014 this fails before the change (current user would be re-inserted) and passes after, so it grades outcome deterministically. Assertions are small, exact ID arrays, not snapshots or pinned strings, so the grader is not brittle. The removed must_be_subscribed assertions are just cleanup of a deleted helper and don't undermine verifiability."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The hidden test only deletes assertions tied to the removed feature and asserts new behavior exclusively through module functions that already exist at the base commit: initialize_with_current_user(), sync_user_ids(), remove_user_ids(), and sorted_user_ids() in stream_create_subscribers_data. It introduces no new names, fields, or helpers. The only thing it pins is the changed behavior itself \u2014 sync_user_ids() now takes the given user-id list verbatim instead of force-retaining the current user \u2014 which is the user-visible outcome of the fix expressed via the pre-existing API, not an implementation choice a solver would have to guess."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product goal (show the channel creator pill in the choose-subscribers box, matching group creation), and the evidence pins down the checkable data-layer consequences: the must-be-subscribed special case for the current user is removed, and syncing the subscriber set to a given list yields exactly that list while initialization with the current user is retained. Together these determine a concrete, verifiable outcome without referencing tests."
}
