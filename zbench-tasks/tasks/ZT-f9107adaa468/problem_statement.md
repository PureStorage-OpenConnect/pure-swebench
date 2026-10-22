## Remove automatic archiving of channels that lose their last subscriber

### Background

In the Zulip server, when the last subscriber is removed from a private channel (a stream with `invite_only=True`), the server currently archives (deactivates) that channel automatically as a side effect of the unsubscription. This is implemented as a dedicated code path in the bulk-unsubscribe logic (in `zerver/actions/streams.py`), which collects the newly vacant private streams after subscriptions are deactivated (a local variable/concept named `new_vacant_private_streams`) and calls the stream-deactivation action on each of them. Because archiving a channel also strips its other roles, this side effect additionally removes the vacated channel from the realm's default streams and fires all the events associated with archiving.

Now that content access to a channel is governed by a richer permissions model (not just the subscriber list), this implicit behavior is surprising and no longer desirable. Administrators who want a vacant channel archived can archive it manually.

### Current behavior

1. A user is the sole subscriber of a private channel.
2. That user unsubscribes (e.g., `DELETE /json/users/me/subscriptions` with the channel name), or an administrator removes them.
3. The unsubscription succeeds, and then the server automatically deactivates the channel: `Stream.deactivated` becomes `True`, the channel is removed from `DefaultStream` if it was a default stream, and archive-related side effects/events occur.

### Required behavior

1. Removing the last subscriber from a private channel must **not** archive it. After the unsubscription:
   - The unsubscribe request succeeds normally: the response lists the channel under `removed` and it does not appear under `not_removed`.
   - The channel remains active: fetching it fresh from the database shows `deactivated == False`.
   - The channel has zero active `Subscription` rows (the unsubscription itself still works as before).
   - No archive side effects occur: the channel is not removed from default streams, and no channel-deactivation action or its associated events are triggered.
2. All other unsubscription behavior (peer-remove events, unsubscribe events, and the stream "delete" events sent to users who lose visibility into a private channel they can no longer access) is unchanged.
3. Remove the `new_vacant_private_streams` code path entirely — the vacant-stream detection, the loop that deactivates them, and any helper logic that exists only to support it. The removal should also eliminate the database query that this code path performed during unsubscription: bulk-unsubscribe flows should issue exactly one fewer database query than before, with no other query-count changes.
4. Vacant *public* channels were already unaffected by this code path; their behavior must not change.

### Notes

- "Archive" and "deactivate" are the same operation on a channel (`Stream.deactivated = True` via the deactivate-stream action). Manual archiving by administrators must continue to work exactly as today; only the automatic trigger on vacancy is being removed.
- Check for and update any user-facing or developer documentation that describes the old auto-archive-on-vacancy behavior (e.g., help center or API changelog text about private channels being deactivated when their last subscriber leaves), so docs match the new behavior.
