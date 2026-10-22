# ZT-eb7eaba52608 -- peer_data: Fetch subscriptions for a user in get_streams_for_user.

- lang: web   issue: #35341   tier: B
- fix: https://github.com/zulip/zulip/commit/eb7eaba526084eb51fcc687e85ba126d59b7070e
- f2p: web/tests/peer_data.test.cjs, web/tests/stream_data.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real engineering task: add on-demand fetching of a user's subscriptions (new peer_data.load_subscriptions_for_user with dedup, retry/backoff, and completeness tracking) and make get_streams_for_user async. The hidden tests grade observable behavior deterministically \u2014 request URL, request-count dedup (one fetch for concurrent callers), retry-then-success and give-up-after-5 paths, 400 vs 500 handling, skipping the fetch when full subscriber data exists, and the resulting subscribed/can_subscribe stream lists. No snapshot pinning or format brittleness; blueslip message assertions are targeted single-line expectations tied to the error-handling behavior under test, and the stream-list assertions use structured deepEqual on data, not rendered output."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "peer_data gains a public async function `load_subscriptions_for_user(user_id: number): Promise<void>` that ensures the given user's channel subscriptions are loaded into the client's peer/subscriber data before resolving.",
    "The subscriptions are fetched via a GET request to `/json/users/<user_id>/channels`; the JSON response contains a field `subscribed_channel_ids`: an array of numeric channel IDs the user is subscribed to.",
    "On success, each channel ID in `subscribed_channel_ids` is recorded as a subscription of that user, so the pre-existing `stream_data.is_user_loaded_and_subscribed(stream_id, user_id)` returns true for those channels.",
    "Concurrent calls of `load_subscriptions_for_user` for the same user must share a single in-flight request: while a fetch is pending, subsequent calls return a promise tied to that fetch rather than issuing another request; likewise, once a user's subscriptions are loaded, further calls make no request.",
    "If full subscriber data is already held for every channel (e.g. every channel's subscribers have been fetched via the pre-existing per-channel fetch path), `load_subscriptions_for_user` resolves without making any request.",
    "On a server error (non-400, e.g. HTTP 500), the fetch is retried with backoff; each retry logs the warning `Failure fetching user's subscribed channels. Retrying.`. After 5 failed retries, it stops and logs the error `Failure fetching user's subscribed channels. Giving up.`. A retry that eventually succeeds records the subscriptions normally.",
    "On an HTTP 400 response, no retry is attempted and the error `Bad request to fetch user's subscribed channels.` is logged.",
    "`stream_data.get_streams_for_user(user_id)` becomes async: it returns a Promise that first ensures the target user's subscriptions are loaded (via the mechanism above) and then resolves to the existing `{subscribed, can_subscribe}` result shape; all call sites must await it.",
    "The pre-existing state-reset function `peer_data.clear_for_testing()` must also clear the newly introduced per-user subscription-loaded state and any pending subscription requests, so a reset module refetches on the next call."
  ],
  "reason": "The test exercises the feature only through a new public peer_data entry point, the REST endpoint URL and its response field, pinned operator-facing log/error wording, retry/dedup semantics, and pre-existing APIs (is_user_loaded_and_subscribed, maybe_fetch_stream_subscribers, clear_for_testing, channel.get as the standard HTTP boundary). All of these are contract surface a ticket would state. The fix's genuinely internal choices \u2014 private caches like fetched_user_subscriptions, the load_subscriptions_for_user_with_retry helper, pending_subscription_requests \u2014 are never referenced by the test, so with the listed requirements in the brief the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives the motivation (lazily-fetched subscriber data leaves get_streams_for_user incomplete), and the evidence plus interface requirements pin down a determinate, checkable contract: the new function name and signature, the exact endpoint and response field, deduplication of in-flight requests, the skip-when-complete condition, exact retry counts and log messages for 500 vs 400, the async conversion of get_streams_for_user, and the reset semantics of clear_for_testing. Two engineers working from this brief would produce compatible implementations."
}
