# ZT-11e334fa8ab7 -- presence_data: Fetch presence data when user card is opened.

- lang: web   issue: #31037   tier: B
- fix: https://github.com/zulip/zulip/commit/11e334fa8ab73069e78781c03dff631994d76067
- f2p: web/tests/buddy_data.test.cjs
- p2p: web/tests/presence.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, assignable frontend feature: fetch presence data on demand when the user card popover opens for users with stale/missing presence. The hidden test grades observable behavior deterministically \u2014 it asserts that user_last_seen_time_status invokes the missing-data callback with the correct user_id and returns an empty string when presence data is absent. No snapshot pinning, no exact long-string or format brittleness (the only string compared is a short translated-status marker consistent with existing test conventions), and the outcome fails before the change and passes after."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The exported function `user_last_seen_time_status(user_id)` in `web/src/buddy_data` gains an optional second parameter: a callback of type `(user_id: number) => void`. Callers that can lazily fetch presence data (e.g. the user card popover) pass this callback so the missing-data case can be handled asynchronously.",
    "When the user's presence record has no last-active timestamp (presence data unavailable or older than the fetched window) and the callback argument is provided, `user_last_seen_time_status` must invoke the callback exactly once with that user's id and return the empty string \"\" instead of the 'Not active in the last year' text; when no callback is provided, existing behavior is unchanged."
  ],
  "reason": "The test's only new binding is an extended signature of `user_last_seen_time_status`, a pre-existing exported cross-module function \u2014 public API within the codebase whose extension a ticket would legitimately dictate (optional missing-data callback, invoked with the user_id, empty-string return as the 'data pending' sentinel). The parameter is positional, so no private name must be guessed; the callback's argument and the \"\" return are asserted contract semantics a brief would state. Test setup uses only pre-existing surface (`presence.presence_info`, `set_presence`). The fix's other internals (fetch_presence_for_popover, the zod schema, the DOM class, 'Loading\u2026' text) are not touched by the test, so no coupling to internal implementation choices."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product goal (fetch precise presence when the user card is open, review long-period strings), and the evidence plus interface requirements pin down the exact observable contract: an optional callback parameter, invoked exactly once with the user id when last_active is missing, with an empty-string return value, and unchanged behavior without the callback. Together these are determinate and checkable."
}
