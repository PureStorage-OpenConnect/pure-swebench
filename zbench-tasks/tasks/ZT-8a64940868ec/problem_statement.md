# Editing a direct message to empty content should save it as "(deleted)"

## Context

Zulip allows users to edit messages they have sent, via the message-edit endpoint (`PATCH /json/messages/{message_id}` with a `content` parameter). As a product convention, when a user edits a message and submits empty content (or content consisting only of whitespace), the message is not left blank; instead its content is replaced with the literal text `(deleted)`, which then goes through normal message rendering and is what gets persisted and displayed.

## Current behavior

This empty-content handling currently works for messages sent to a channel (stream): editing a stream message and submitting content such as `" "` results in the stored message content being `(deleted)`.

However, for direct messages (DMs / private messages), the same edit does not produce this result. When a user edits one of their direct messages to empty or whitespace-only content and saves it, the message ends up showing nothing rather than the `(deleted)` placeholder.

## Required behavior

Editing a message to empty or whitespace-only content must behave identically regardless of whether the message is a channel message or a direct message:

1. A user edits one of their own direct messages via `PATCH /json/messages/{message_id}`, passing a `content` value that is empty or contains only whitespace (e.g. `" "`).
2. The request must succeed (a normal JSON success response, not an error).
3. After the edit, the persisted content of that message must be exactly the string `(deleted)` — the same placeholder already used for channel messages edited to empty content.

The existing behavior for channel messages must be preserved unchanged: editing a channel message to empty/whitespace-only content continues to succeed and store `(deleted)` as the message content.

## Notes

- "Empty content" means the submitted content is empty after stripping whitespace; a single space must be treated the same as an empty string.
- The fix should apply the placeholder substitution wherever message-edit content is normalized, so that the code path taken by direct messages gets the same treatment as the one taken by channel messages, rather than special-casing one message type in the API layer.
