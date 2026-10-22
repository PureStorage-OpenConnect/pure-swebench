# Live-update user names in reaction pills

## Context

In the Zulip web client, emoji reactions on a message are shown as "reaction pills" beneath the message. Depending on the user's display settings, a pill can show vote text that includes the display names of the users who reacted (e.g., "Alice, Bob"), rather than just a count.

## Current behavior

When a user's full name changes (delivered to the client via a realm-user update event), the reaction tooltip information is updated, but the vote text rendered inside the reaction pills themselves is not. Rendered messages continue to show the user's old name in reaction pills until the message is re-rendered for some other reason.

## Required behavior

When a realm-user update event changes a user's full name, the client must re-render the reaction vote text on every currently rendered message that has a reaction from that user, so the pills immediately show the new name. Messages on which the user has not reacted must be left alone.

Concretely:

- Wire the realm-user full-name-update event handling path to notify the `reactions` module of the changed user's ID.
- The `reactions` module must find all affected rendered messages by iterating the rendered message lists (via `message_lists.all_rendered_message_lists()`) and inspecting each message's reactions.
- For each rendered message whose reactions include the given user, the module's existing per-message vote-text re-render routine (`update_vote_text_on_message`) must run exactly once for that message — even if the user has multiple reactions (different emoji) on the same message.
- If the given user has no reactions on any rendered message, no vote-text update may occur at all.

## Interface requirements

- The `reactions` module gains a public function `update_user_full_name(user_id: number)`, invoked from the realm-user update event path when a user's full name changes, so that reaction vote text (which can contain display names) stays current.
- `update_user_full_name(user_id)` must enumerate rendered messages via the existing `message_lists.all_rendered_message_lists()` API and, for each message whose reactions include `user_id`, trigger the module's existing per-message vote-text re-render routine `update_vote_text_on_message(message)` exactly once per affected message.
- For a `user_id` that appears in no reactions on any rendered message, `update_user_full_name` must perform no vote-text updates.
