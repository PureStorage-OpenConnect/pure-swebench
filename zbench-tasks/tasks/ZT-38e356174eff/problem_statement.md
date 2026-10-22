## Optimize the recipient-accessibility check when limited guests send direct messages

### Context

Zulip supports restricting which users a guest can see ("limited guests", controlled by the realm's user-access settings). When a user with limited user access sends a direct message, the server may need to send `realm_user` creation events so that participants who could not previously access each other become visible to one another. This logic lives in `get_recipients_for_user_creation_events` in the message-send code path.

### Observed behavior

Whenever a limited guest sends a DM to another user, the code path ends up calling the fairly expensive `get_accessible_user_ids` check to compute the full set of users the sender can access. This happens on **every** DM send by such a user, so the cost is paid repeatedly and can add noticeable latency to sending each direct message.

### Expected behavior

Sending a DM as a limited guest should not require computing the full set of accessible user IDs on every message. The queries used by `get_recipients_for_user_creation_events` should be optimized to filter down to only the set of users actually relevant to the message being sent (i.e., the participants in the conversation), rather than performing a broad accessibility computation across the realm.

### Notes

A longer-term idea is to short-circuit the check entirely when a persisted direct-message-group (`Huddle`) object already exists for the conversation — since its existence would imply the authorization check already passed when the conversation was first created, turning this from an "every DM" cost into a "first DM in a new conversation" cost. However, that depends on broader changes to how DM conversations are persisted. Independently of that, narrowing the queries to just the relevant users is worthwhile on its own and is the goal of this task.
