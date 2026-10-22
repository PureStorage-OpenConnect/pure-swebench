## Performance: expensive user-accessibility computation on every DM sent by a limited guest

### Context

Zulip supports restricting which users a guest can see (the "limited guest" / `can_access_all_users_group` feature). When a user becomes newly visible to such a guest — for example, because they exchange a direct message for the first time — the server must send that guest the appropriate user-creation events. This logic lives in `get_recipients_for_user_creation_events` (in the message-send code path, `zerver/actions/message_send.py`).

### Observed behavior

Whenever a limited guest sends a direct message to another user, `get_recipients_for_user_creation_events` ends up performing a `get_accessible_user_ids` check. That check is fairly expensive: it computes the full set of user IDs accessible to the guest across the realm (scanning subscriptions, DM history, etc.), even though the only users whose accessibility actually matters here are the small set of participants in the message being sent.

Because this runs on the hot path of *every* DM a limited guest sends, it adds noticeable, unnecessary latency to a very common operation.

### Expected behavior

Sending a DM as a limited guest should not require computing the guest's entire accessible-user set on every send. The queries in this code path should be optimized to filter down to just the set of relevant users (the participants involved in the message) when determining whether user-creation events need to be sent, rather than materializing the full accessible-user list.

A further possible optimization (worth keeping in mind, but not a prerequisite): if a `Huddle` object already exists for the DM recipients, the participants have necessarily already messaged each other, so any further authorization/accessibility check could be skipped entirely — turning this from an every-DM cost into a first-DM-in-a-new-group cost. Even if that short-circuit is added later, narrowing the queries to the relevant users remains useful on its own.
