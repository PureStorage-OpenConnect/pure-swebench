# Improve the empty message feed for private channels the user cannot access

## Context

In the Zulip web app, some users can see that a private channel exists (and manage its metadata) without having permission to access its content or to subscribe themselves. An example is an administrator who can see and administer a private channel's settings but does not have content access.

When such a user navigates to that private channel's message view in the web app, the message feed is empty (they cannot see any messages). Currently, two things go wrong in this state:

1. **Trailing bookend:** The message list renders a trailing "you are not subscribed" bookend, typically with a subscribe affordance. This is misleading, because the user is not allowed to subscribe to this channel at all.
2. **Empty-feed placeholder:** The empty-narrow banner does not clearly explain why the feed is empty.

## Required behavior

When the web app is narrowed to a **private channel** (`invite_only`) that the current user is **not subscribed to** and is **not allowed to subscribe to**:

1. **No bookend at all.** The message list must not render the trailing subscribe/unsubscribe bookend. The bookend rendering step must be skipped entirely in this case — not rendered with different text.
2. **Improved empty-feed placeholder.** The empty-narrow banner must display exactly this user-facing message (marked for translation):

   > You are not allowed to view messages in this private channel.

   This is a title-only notice: no additional description text, links, or extra HTML beyond the standard empty-feed notice structure.

Existing behavior must be preserved in all other cases: users who are unsubscribed from a channel they *can* subscribe to should continue to see the current bookend and empty-feed behavior, and subscribed users' views are unchanged.

## Interface requirements

- When narrowing to a private channel (`invite_only`) that the user is not subscribed to and is not allowed to subscribe to, the empty-narrow banner must show the user-facing message "You are not allowed to view messages in this private channel." (marked for translation, title only, with no extra HTML).
- Whether the user is allowed to subscribe to a channel must be determined via the pre-existing exported helper `stream_data.can_toggle_subscription(sub)`. Any code deciding subscribe-related UI for a channel (including the bookend logic and the empty-narrow banner logic described above) must route through this function rather than reimplementing the permission check inline.
- When the user is not subscribed to the narrowed channel and `stream_data.can_toggle_subscription(sub)` returns `false`, the message list must not render any trailing bookend — the code path that renders the trailing bookend is skipped entirely for that channel.

## Notes for implementation

- The bookend logic lives in the message list's handling of the trailing bookend (the code that decides whether to show subscribed/unsubscribed bookends for a channel narrow).
- The empty-feed placeholder logic lives in the empty-narrow banner code that selects which notice to show for a channel narrow (alongside existing cases such as nonexistent channels and empty channels).
- The new empty-feed case applies specifically when the channel is known to the client and marked `invite_only`, the user is unsubscribed, and `can_toggle_subscription` reports they cannot subscribe. It should take precedence over the generic unsubscribed/empty-channel notices for that narrow.
