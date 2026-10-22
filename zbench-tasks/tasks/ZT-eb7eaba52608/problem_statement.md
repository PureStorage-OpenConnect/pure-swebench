# Load a user's full subscription list on demand in the web client's peer data

## Background

In the Zulip web client, the `peer_data` module (`web/src/peer_data.ts`) tracks which users are subscribed to which channels (streams) via per-stream subscriber sets. The client recently moved to lazily fetching channel subscriber data: subscriber sets for a channel are only guaranteed complete after the per-channel fetch path (`peer_data.maybe_fetch_stream_subscribers(stream_id)`) has run for that channel. As a result, the client can no longer assume it knows every channel a given user is subscribed to.

This breaks `stream_data.get_streams_for_user(user_id)` (`web/src/stream_data.ts`), which computes, for a target user, the channels they are subscribed to and the channels the current user could subscribe them to, returning an object of the shape `{subscribed, can_subscribe}`. Today it consults the possibly-incomplete local subscriber sets synchronously, so it can silently omit channels the target user is actually subscribed to.

## Required behavior

Add a way to fetch a single user's complete subscription list from the server and merge it into `peer_data`'s per-stream subscriber sets, and make `stream_data.get_streams_for_user` use it so its results are based on complete data.

### Fetching a user's subscriptions

- `peer_data` exposes a new public async function `load_subscriptions_for_user(user_id: number): Promise<void>` that ensures the given user's channel subscriptions are loaded into the client's subscriber data before the returned promise resolves.
- The data is fetched with a GET request to `/json/users/<user_id>/channels`. The JSON response contains a field `subscribed_channel_ids`: an array of numeric channel IDs the user is subscribed to.
- On success, each channel ID in `subscribed_channel_ids` is recorded as a subscription of that user in the local subscriber data. After this, the pre-existing `stream_data.is_user_loaded_and_subscribed(stream_id, user_id)` must return `true` for each of those channels for that user.
- **Request deduplication:** concurrent calls for the same user must share a single in-flight request. While a fetch for a user is pending, additional calls for that user return a promise tied to the pending fetch rather than issuing a second request. Once a user's subscriptions have been loaded, subsequent calls for that user resolve without making any request.
- **Skip when data is already complete:** if the client already holds full subscriber data for every channel (for example, because every channel's subscribers were previously fetched via `maybe_fetch_stream_subscribers`), `load_subscriptions_for_user` resolves without issuing any request — the local data already determines the user's subscriptions.

### Error handling

Use the client's standard logging module (blueslip) with these exact messages:

- On a server error other than HTTP 400 (e.g. HTTP 500), retry the fetch with backoff. Each retry logs the warning `Failure fetching user's subscribed channels. Retrying.`. After 5 failed retries, stop retrying, log the error `Failure fetching user's subscribed channels. Giving up.`, and resolve (the promise should not hang or reject unhandled).
- If a retry eventually succeeds (e.g. two failures followed by a success), the subscriptions are recorded normally, exactly as on a first-try success.
- On an HTTP 400 response, do not retry; log the error `Bad request to fetch user's subscribed channels.` and stop.

### `stream_data.get_streams_for_user` becomes async

- `get_streams_for_user(user_id)` now returns a Promise. It first ensures the target user's subscriptions are loaded (via the mechanism above), then resolves to the same `{subscribed, can_subscribe}` result shape and semantics as before.
- Update every call site of `get_streams_for_user` in the web client to await the result.

### State reset

- The pre-existing state-reset helper `peer_data.clear_for_testing()` must also clear the new per-user "subscriptions loaded" state and any pending per-user subscription requests, so that after a reset the next `load_subscriptions_for_user` call fetches again.

## Interface requirements

- `peer_data` gains a public async function `load_subscriptions_for_user(user_id: number): Promise<void>` that ensures the given user's channel subscriptions are loaded into the client's peer/subscriber data before resolving.
- The subscriptions are fetched via a GET request to `/json/users/<user_id>/channels`; the JSON response contains a field `subscribed_channel_ids`: an array of numeric channel IDs the user is subscribed to.
- On success, each channel ID in `subscribed_channel_ids` is recorded as a subscription of that user, so the pre-existing `stream_data.is_user_loaded_and_subscribed(stream_id, user_id)` returns `true` for those channels.
- Concurrent calls of `load_subscriptions_for_user` for the same user share a single in-flight request; once loaded, further calls make no request.
- If full subscriber data is already held for every channel, `load_subscriptions_for_user` resolves without making any request.
- On a server error (non-400, e.g. HTTP 500), the fetch is retried with backoff, logging the warning `Failure fetching user's subscribed channels. Retrying.` per retry; after 5 failed retries it stops and logs the error `Failure fetching user's subscribed channels. Giving up.`. A retry that eventually succeeds records the subscriptions normally.
- On an HTTP 400 response, no retry is attempted and the error `Bad request to fetch user's subscribed channels.` is logged.
- `stream_data.get_streams_for_user(user_id)` becomes async: it returns a Promise that first ensures the target user's subscriptions are loaded and then resolves to the existing `{subscribed, can_subscribe}` result shape; all call sites must await it.
- `peer_data.clear_for_testing()` must also clear the newly introduced per-user subscription-loaded state and any pending subscription requests, so a reset module refetches on the next call.
