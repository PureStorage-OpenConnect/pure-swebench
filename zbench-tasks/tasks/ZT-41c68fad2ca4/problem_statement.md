# Show the channel creator as a pill in the "choose subscribers" box during channel creation

## Context

In the Zulip web app, when a user creates a new channel (stream), the creation form includes a "choose subscribers" section: a pill-style input where users can be added to or removed from the set of initial subscribers, backed by a data module (`web/src/stream_create_subscribers_data.ts` and its consumers in the stream-creation UI) that tracks the chosen user IDs. Zulip also has a user-group creation flow with an analogous member-selection widget, and that flow already handles the creator correctly: the creator is displayed as a pill in the input when they are going to be added as a member of the new group.

## Current behavior

The channel-creation subscriber chooser treats the creating user (the current user) as a special case rather than as an ordinary entry in the subscriber set:

- The creator is not rendered as a pill in the "choose subscribers" input the way other chosen subscribers are (and the way the group-creation flow renders the group creator).
- The data layer enforces that the current user "must be subscribed" when they are not an administrator: non-admin creators cannot be removed from the subscriber set, while admins can be.
- When the chosen-subscriber set is synchronized from the pill widget's contents, the current user is special-cased: if the current user is already in the set, syncing to a list that omits them does not remove them; if they have been removed, syncing does not re-add them. In other words, the synchronized result is not simply the provided list.

## Required behavior

Make the channel-creation flow handle the creator the same way the group-creation flow handles the group creator:

1. **Creator pill.** When a new channel is being created and the creator will be among its initial subscribers, the creator must be shown as a pill in the "choose subscribers" input, visually consistent with how the group creator is shown in the group-creation member chooser.
2. **No "must be subscribed" special case.** Remove the concept that the current user is forced to remain in the subscriber set. The creator must be removable from the chosen-subscriber set exactly like any other user, regardless of whether the creator is an administrator. The subscriber-count/list display below the input should likewise reflect the actual chosen set with no forced inclusion of the current user.
3. **Exact synchronization.** When the chosen-subscriber data is synchronized to a given list of user IDs (i.e., the pill widget's current contents), the resulting set must be exactly that list. Concretely: if the set was initialized to contain only the current user and is then synchronized to two other users' IDs, the resulting sorted set must contain exactly those two users and not the current user.
4. **Initialization unchanged.** The chooser must still start out with the current user in the chosen set when the channel-creation form is opened (they are the default initial subscriber); the change is that this initial inclusion is an ordinary, removable entry, not an enforced one.

Any UI affordances that previously depended on the "must be subscribed" rule (e.g., hiding or disabling the remove control on the creator's row for non-admins) should be updated so the creator's entry behaves like any other user's entry.

## Acceptance criteria

- Creating a channel with the creator left in the chooser shows the creator's pill in the input and subscribes them on creation.
- A non-admin creator can remove themselves from the chosen subscribers before creating the channel, and the channel is then created without them.
- Synchronizing the chosen-subscriber data with a list of user IDs yields exactly that list — the current user is neither force-retained when absent from the list nor force-excluded when present.
- The group-creation flow's existing creator-pill behavior is unchanged and the channel flow now matches it.
