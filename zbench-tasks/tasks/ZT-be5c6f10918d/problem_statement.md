# Prevent stale cached `raw_content` on messages in unsubscribed channels

## Background

The Zulip web app keeps client-side message objects in `web/src/message_store`. For some flows (quoting a message, editing, and similar code paths), the client fetches a message's `raw_content` — the original Markdown source — from the server and caches it on the message object (historically via direct assignment to `message.raw_content`).

The client keeps a cached message's rendered and raw content up to date by applying `update_message` events. However, the client only receives such events for messages it is subscribed to. For a stream (channel) message in a channel the current user is **not** subscribed to (e.g., a message fetched while viewing a public channel without subscribing), no content-update events will arrive if that message is later edited.

## The bug

Because of this, a cached `raw_content` value on a message in an unsubscribed channel can silently become stale: the message gets edited on the server, the client never hears about it, and the client later reuses the outdated Markdown (for example when quoting the message). It is a rare race, but the cached value is simply wrong when it happens.

## Required behavior

Introduce a single guarded entry point in the `message_store` module for caching raw content, and route all code paths that currently assign `message.raw_content` directly through it. The guard must behave as follows:

1. **Safe to cache:** For a stream message in a channel the current user IS subscribed to (i.e., the client will receive update events for it), store the provided raw content on the message (`message.raw_content` is set to the given value).
2. **Unsafe to cache:** For a stream message in a channel the current user is NOT subscribed to, do NOT store the provided value. Additionally, set `message.raw_content` to `undefined`, so that any previously (accidentally) cached raw content is cleared and a stale version can never be reused. This clearing must happen even if the message already had a `raw_content` value before the call.

Subscription status should be determined from the client's stream/subscription data (e.g., via the existing `stream_data` subscription lookup by `stream_id`).

All existing sites that fetch `raw_content` from the server and cache it on a message object (message edit/quoting flows, and any refresh of a cached message's content in `message_store`) must be updated to go through this new function rather than assigning `raw_content` directly.

## Interface requirements

- The `message_store` module must export a function `maybe_update_raw_content(message, raw_content)`. This is the single entry point callers use when caching a message's raw (Markdown) content locally, replacing direct assignment to `message.raw_content`.
- Semantics: for a stream message in a channel the current user IS subscribed to, `maybe_update_raw_content` sets `message.raw_content` to the provided value.
- Semantics for unsafe caching: for a stream message in a channel the current user is NOT subscribed to (where content-update events will not be received), `maybe_update_raw_content` must NOT store the provided value and must set `message.raw_content` to `undefined`, clearing any previously cached raw content so a stale version cannot be reused.

## Notes

- The observable outcome to verify: given a stream message object with a `stream_id`, calling `maybe_update_raw_content(message, "hello world")` results in `message.raw_content === "hello world"` when the user is subscribed to that channel, and `message.raw_content === undefined` when not subscribed — including the case where the message previously had some cached `raw_content` value.
- Message-update event handling for stream messages can assume the events it processes are for subscribed channels, since those are the only channels events arrive for.
