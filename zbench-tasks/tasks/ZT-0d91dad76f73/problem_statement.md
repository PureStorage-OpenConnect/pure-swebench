# Hide DM conversations involving deactivated users in the collapsed left-sidebar DM list

## Background

Zulip's left sidebar shows a list of recent direct message (DM) conversations. The data for this list is produced in the web client by `web/src/pm_list_data.ts`:

- `get_conversations()` builds a display object for each recent DM conversation (recipients string, unread count, URL, activity state, etc.).
- `get_list_info(zoomed)` decides which conversations are actually rendered. In the unzoomed (collapsed/default) state, the list is capped at the 8 most recent conversations (`max_conversations_to_show`), with an exception that conversations with unread messages, and the currently-active conversation, are always shown; everything that doesn't fit is summarized by a "more conversations" row whose unread badge is `more_conversations_unread_count`. In the zoomed (expanded, "more conversations") state, all conversations are shown.

Currently, DM conversations with deactivated users are still shown in the collapsed list. Since no further messages can be sent to a deactivated user, these conversations don't need quick access and just take up space.

## Required behavior

Treat DM conversations that involve a deactivated user similarly to muted topics: hide them from the default (unzoomed) view of the left-sidebar DM list, while still showing them in the zoomed "more conversations" view.

A conversation counts as "involving a deactivated user" when **any** participant is a deactivated account. This applies to both 1:1 DMs and group DMs (e.g., a group DM with Bob and Cardelio is hidden if Bob is deactivated, even though Cardelio is active).

Concretely, `get_list_info(zoomed)` must behave as follows:

1. **Unzoomed (`zoomed === false`):**
   - Conversations that include any deactivated user are excluded from `conversations_to_be_shown`.
   - The cap of 8 most-recent conversations is applied **after** this exclusion: up to 8 of the remaining eligible conversations are shown. Filtered-out conversations must not consume any of the 8 slots. Example: with 5 recent 1:1 conversations of which one partner is deactivated, exactly 4 are shown; with 13 total conversations of which 2 involve a deactivated user, the 8 most recent of the remaining 11 are shown.
   - Unread messages in the excluded (deactivated-user) conversations count toward `more_conversations_unread_count`, together with unreads from any conversations dropped by the cap. Example: 13 conversations, 2 involving a deactivated user, each conversation having 1 unread — since conversations with unreads bypass the cap, all 11 eligible conversations are shown and `more_conversations_unread_count` is 2 (the unreads from the 2 hidden deactivated-user conversations).

2. **Zoomed (`zoomed === true`):**
   - All conversations are shown, including those involving deactivated users, in the usual most-recent-first order.
   - `more_conversations_unread_count` is 0.

Deactivation state can change at runtime (a user can be deactivated or reactivated during a session); the list must reflect the current state whenever it is computed.

## Interface requirements

- The per-conversation display object returned by `pm_list_data.get_conversations()` currently has a boolean field `is_deactivated`. Rename it to `includes_deactivated_user`, and make it true when **any** participant in the conversation is a deactivated account (the old field only reflected the single other user in a 1:1 DM). Update all consumers of this field — including the sidebar rendering templates/logic that use it (e.g., for styling deactivated conversations) — to the new name and semantics.
- In the unzoomed direct-message list produced by `get_list_info`, conversations that include any deactivated user are excluded from `conversations_to_be_shown`, and their unread messages are added to `more_conversations_unread_count`.
- In the zoomed direct-message list, all conversations appear (including those with deactivated users) and `more_conversations_unread_count` is 0.
- The unzoomed cap of 8 most-recent conversations (`max_conversations_to_show`) is applied after excluding deactivated-user conversations, so up to 8 eligible conversations are shown rather than 8 slots being consumed by filtered-out entries.
