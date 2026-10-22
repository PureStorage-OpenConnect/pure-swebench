# Improve time-limit handling and error messages for whole-topic moves (`propagate_mode="change_all"`)

## Background

Zulip organizations can configure a time limit that restricts how long non-moderator users may move messages to a different topic or channel (`move_messages_within_stream_limit_seconds` / `move_messages_between_streams_limit_seconds`, plus the general message-edit deadline). Moves are requested via the message-edit endpoint `PATCH /json/messages/{message_id}` with a `propagate_mode` parameter (`change_one`, `change_later`, or `change_all`) and a new `topic` and/or `stream_id`.

When a user requests a `change_all` move (move every message in the topic), the time limits interact badly with the fact that the request names a single message:

1. **Per-message deadline applied to a topic-wide operation.** If the specific message id named in the request is itself older than the move deadline, the request is rejected outright with a per-message error such as "The time limit for editing this message's topic has passed." or "The time limit for editing this message's channel has passed" — even though the user is asking to move the whole topic, and some (or all) other messages in the topic may still be within the limit. Which error the user gets depends arbitrarily on which message they happened to click on.
2. **Misleading wording when the whole topic is too old.** When a `change_all` move fails because *no* message in the topic is within the time limit, the error says "The time limit for editing this message's topic has passed." — phrased as if it were about a single message rather than about moving the topic.

## Required behavior

All of the following apply to requests from users who are subject to the realm's message-move time limits (i.e., non-moderators in realms where a limit is configured). Moderators and realms without limits are unaffected.

### 1. `change_all` must not be gated on the requested message's own age

For a move request with `propagate_mode="change_all"` (topic change, channel change, or both), the per-message edit/move deadline check must **not** be applied to the message id named in the request. The request may reference *any* message in the topic, including one older than the deadline. The only time-limit enforcement for `change_all` is the topic-wide recency rule described below.

`propagate_mode="change_one"` (and `change_later`) keep their existing behavior: a channel move of a single message older than the limit is still rejected with the existing error "The time limit for editing this message's channel has passed" (and analogously for topic edits).

### 2. Partial block: report how many messages can be moved

When a `change_all` move is blocked because only some of the topic's messages fall within the time limit, the request must fail with the existing user-facing error:

> You only have permission to move the N/M most recent messages in this topic.

where **M** is the total number of messages in the topic and **N** is the number that fall within the time limit. This error (with correct N and M counts) must be produced **even when the message id named in the request is itself outside the limit** — the request must not short-circuit into a per-message rejection. Example: a topic with 5 messages of which 3 are recent enough must produce "You only have permission to move the 3/5 most recent messages in this topic." regardless of which of the 5 messages the request names.

When this error occurs, no messages may be moved: the topic's messages must all remain in the original channel/topic, and nothing may appear in the destination.

The JSON error response for this case must continue to include the `first_message_id_allowed_to_move` field, identifying the oldest message the user is permitted to move.

### 3. Full block: clearer error wording

When a `change_all` move fails because **zero** messages in the topic fall within the time limit, the request must fail with the user-facing error:

> The time limit for moving this topic has passed.

This replaces the previous wording "The time limit for editing this message's topic has passed." for this situation. This applies wherever a whole-topic move is fully blocked by the time limit, including topic moves triggered by resolving/unresolving a topic.

## Interface requirements

- For non-moderator users in realms with a message-move time limit, a move request with `propagate_mode="change_all"` must not be rejected by the per-message edit/move deadline check; only the topic-wide recency limit applies, so the request may reference any message in the topic (including one older than the deadline).
- When a `change_all` move is partially blocked by the time limit, the request fails with the existing user-facing error "You only have permission to move the N/M most recent messages in this topic.", where M is the total number of messages in the topic and N is how many fall within the time limit. These counts must be reported even when the message id named in the request is itself outside the limit, and the topic's messages must be left unmoved.
- When a `change_all` move is fully blocked because zero messages in the topic fall within the time limit, the request fails with the user-facing error "The time limit for moving this topic has passed." (replacing the previous wording "The time limit for editing this message's topic has passed.").

## Notes

- Update API documentation / changelog entries as appropriate for the changed error behavior, following the codebase's conventions.
- Exact error strings matter (punctuation included): the partial-block error ends with a period; the `change_one` channel-move error "The time limit for editing this message's channel has passed" does not.
