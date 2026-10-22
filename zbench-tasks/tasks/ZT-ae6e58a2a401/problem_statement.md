# Add message link fields to the send-message API response

## Background

Bots and integrations that send messages via `POST /api/v1/messages` often want to link back to the message they just sent — for example, a GitHub bot that opens a Zulip topic for an issue and then wants to post a comment on GitHub linking to that topic. Today the response contains only the new message's `id`. To build a working link, an API client has to reimplement Zulip's URL-fragment encoding for channel names and topics (the `#narrow/channel/<id>-<name>/topic/<encoded-topic>/near/<id>` scheme), which is undocumented and easy to get wrong.

The web app already solves this internally: its "Copy link to message" action produces both a permanent `/near/` URL for a message and a Markdown link of the form `[#<channel> > <topic> @ 💬](<url>)`. The server should expose the same information directly in the send-message API response.

## Required behavior

Extend the success response of `POST /api/v1/messages` with two new string fields, `message_url` and `message_link`.

### `message_url`

The absolute, permanent URL of the just-sent message — a near-narrow link on the realm's base URL targeting the message directly:

- **Channel message (sender has metadata access to the channel):**
  `<realm-url>/#narrow/channel/<stream-id>-<hyphenated-stream-name>/topic/<encoded-topic>/near/<message-id>`
  using Zulip's standard narrow-URL encoding (e.g. a topic `Test topic` encodes as `Test.20topic`; a stream name `group access channel` appears as `group-access-channel`). Example: `http://zulip.example.com/#narrow/channel/5-Verona/topic/Test.20topic/near/123`.
- **Channel message (sender lacks metadata access — see below):**
  the ID-only narrow form that omits the channel name entirely:
  `<realm-url>/#narrow/channel/<stream-id>/topic/<encoded-topic>/near/<message-id>`.
  The channel's name must not appear anywhere in the URL.
- **Direct message:**
  `<realm-url>/#narrow/dm/<slug>/near/<message-id>`, where `<slug>` is the recipient user IDs (including the sender for a DM the sender is part of) sorted ascending and joined with commas, e.g. `.../#narrow/dm/10,12/near/456`.

These URLs must match what the web app itself generates for the same message, so that they resolve identically in all clients.

### `message_link`

A ready-to-paste Zulip Markdown link matching the web app's "Copy link to message" output:

- **Channel message where the sender has metadata access:**
  `[#<channel name> > <topic> @ 💬](<message_url>)` — the raw (unencoded) channel name and topic, the literal `💬` emoji, and the same absolute URL as `message_url` embedded as the link target. Embedding the absolute URL (not a relative fragment) keeps the link usable when pasted outside Zulip.
- **Direct message:** there is no channel name and no standard label, so `message_link` is simply the same string as `message_url` (the bare URL).
- **Channel message where the sender lacks metadata access:** `message_link` is also just the bare URL (same string as `message_url`), since rendering the labeled form would leak the channel name.

## Metadata access: who gets the channel name

Whether the channel name appears in the URL/link depends on whether the *sender* has metadata access to the channel (the right to know its name). This matters because it is possible to send to a channel without such access — notably, a bot may post to a private channel through its owner's subscription without being subscribed itself. Required outcomes:

1. **Directly subscribed sender:** has metadata access; gets the named URL form and the full Markdown `message_link`. This must hold even when the sender is a long-term-idle subscriber: idle subscribers may be excluded from the recipient bookkeeping computed during send, but the sender's subscription is already confirmed while authorizing the send, and metadata access must be resolved from that authorization, not from the recipient bookkeeping.
2. **Sender with group-derived access only:** a sender who is not subscribed but can access the channel purely through a group-based channel permission (e.g. membership in the channel's `can_subscribe_group`) also has metadata access and gets the named URL form and the full Markdown link. The send-authorization path already loads the sender's recursive group memberships in this case; metadata access must be resolved from those already-loaded memberships.
3. **Non-subscribed bot posting via its owner's subscription to a private channel:** can send, but has no metadata access. It must receive the ID-only URL (no channel name anywhere in it) and a bare-URL `message_link`.

## Performance constraint

Computing these two fields must not add any database queries to the message-send path. In particular, when the sender's group memberships were *not* already loaded during send authorization (the write-only-bot case above), do not fetch them — treat them as empty and conservatively fall back to the ID-only URL. A private-channel send by such a bot must complete in exactly the same total number of database queries as the send path without this feature.

## Interface requirements

- The `POST /api/v1/messages` response gains a string field `message_url`: the absolute permanent URL (near-narrow link) of the sent message, e.g. `https://<realm>/#narrow/channel/<id>-<name>/topic/<encoded-topic>/near/<message-id>` for channel messages and `https://<realm>/#narrow/dm/<comma-joined-sorted-user-ids>/near/<message-id>` for direct messages.
- The `POST /api/v1/messages` response gains a string field `message_link`: a Markdown link matching the web app's "Copy link to message" format, `[#<channel name> > <topic> @ 💬](<message_url>)`, embedding the same absolute URL as `message_url`.
- For direct messages, `message_link` is simply equal to `message_url` (the bare URL).
- If the sender lacks metadata access to the channel (e.g. a non-subscribed write-only bot posting to a private channel via its owner's subscription), `message_url` must omit the channel name and use the ID-only narrow form `/#narrow/channel/<id>/topic/...`, so the channel name is not leaked; in that case `message_link` is also just the bare URL.
- A sender who is directly subscribed to the channel has metadata access and gets the channel name in the URL and the full Markdown `message_link`; this must hold even for long-term-idle subscribers (the subscription confirmed while authorizing the send suffices, independent of recipient-row computation).
- A sender whose channel access derives solely from a group-based permission (e.g. membership in the channel's `can_subscribe_group`), without a direct subscription, also has metadata access and gets the channel name in the URL and the full Markdown link; metadata access is resolved from the recursive group memberships already loaded to authorize the send.
- Resolving the sender's metadata access must not add any database queries to the send path: when the sender's group memberships were not loaded during send authorization (e.g. a bot posting via its owner's subscription), they are treated as empty rather than fetched, conservatively omitting the channel name. A full private-channel bot send must complete in the same total query count as the baseline send path.

## Documentation

Update the API changelog/feature level and the `POST /messages` API documentation to describe the two new response fields.
