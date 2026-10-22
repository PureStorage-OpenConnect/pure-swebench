## Reminder for a channel message generates an inaccurate topic link

### Observed behavior
When a user schedules a reminder for a message in a channel, the reminder that is later delivered includes a link to the channel/topic where the original message lives. The syntax used to render that topic reference does not incorporate the ID of the specific message the reminder was set on. Instead, the generated `/with/` narrow link resolves using the latest message in that topic at the time the reminder was created.

As a result, the link in the reminder can point at the wrong place: rather than anchoring on the exact message the user asked to be reminded about, it anchors on whatever message happened to be most recent in the topic when the reminder was scheduled. This is not the optimal `/with/` link for describing the channel/topic in the reminder.

### Expected behavior
The topic link included in a reminder for a channel message should reference the specific message the reminder was set on, so the resulting `/with/` link takes the user directly to that message rather than to a different (latest-at-scheduling-time) message in the topic.
