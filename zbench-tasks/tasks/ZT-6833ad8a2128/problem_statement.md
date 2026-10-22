# Real-time sync for channel access granted via `can_add_subscribers_group`

## Background

In Zulip, a private channel's `can_add_subscribers_group` setting names a user group; users in that group (directly or via subgroup membership, i.e. recursive group membership) have permission to add subscribers to the channel. Having this permission grants those users **content access** to the channel — and content access implies **metadata access**, meaning the channel should appear in the user's client even if they are not subscribed and are not otherwise able to see it (e.g. it is a private channel and they are not a subscriber, admin, or member of any other permission group that would reveal it).

Clients learn about which channels they can see through the events system: when a user gains access to a channel they previously could not see, the server must send that user a channel-creation event (a `stream` event with `op: "create"` carrying the channel's data) so the client can render it, typically followed by subscriber-peer information (`subscription` events with `op: "peer_add"`) so the client knows who is subscribed. Conversely, when a user loses access to a channel they can now no longer see at all, the server must send that user a channel-deletion event (a `stream` event with `op: "delete"`) so the client removes it.

This event flow works correctly for the subscription-change code paths (`bulk_add_subscriptions` and friends), but access via `can_add_subscribers_group` can change through two *other* kinds of operations, and those paths do not currently send the right events.

## Current (buggy) behavior

1. **Changing a channel's group-based permission setting.** When `do_change_stream_group_based_setting` changes a setting such as `can_add_subscribers_group`, users whose metadata/content access to the channel changes as a result are not handled correctly. A user who *gains* access this way does not receive a channel-creation event (they only see a channel-permissions-update event for a channel their client doesn't know about, or nothing usable); a user who *loses* access this way similarly does not receive a channel-deletion event.

2. **Changing group membership.** Operations that modify user-group membership — adding/removing users to/from groups, and adding/removing subgroups of a group — can change which users satisfy a channel's `can_add_subscribers_group`, and therefore who has content access to that channel. These code paths (`bulk_add_members_to_user_groups`, `bulk_remove_members_from_user_groups`, `add_subgroups_to_user_group`, `remove_subgroups_from_user_group`) currently send only the user-group update events; they do not send channel creation/deletion events (or peer-subscriber events) to users whose channel access changed as a side effect.

Concretely: if a private channel's `can_add_subscribers_group` is (or contains) group `G`, and a user's membership in `G` changes via subgroup addition/removal or member addition/removal, that user's client is never told to show or hide the channel.

## Required behavior

For every operation that can change whether a user has content/metadata access to a channel via `can_add_subscribers_group` — both direct changes to the channel setting and user-group membership/subgroup changes — the server must compute the set of users whose access changed and send them the appropriate events:

- **Gaining access** to a channel the user could not previously see: the user must receive a channel-creation (`stream` / `op: "create"`) event for that channel, followed by subscriber-peer information (`subscription` / `op: "peer_add"`) about the channel's existing subscribers. When a subgroup is added to a group used in a private channel's `can_add_subscribers_group`, a member of that subgroup who thereby gains access must receive, in order: the user-group `add_subgroups` update event, then the channel-creation event, then the peer-add event(s).
- **Losing access** to a channel the user can no longer see at all: the user must receive a channel-deletion (`stream` / `op: "delete"`) event. When a subgroup is removed from a group used in a private channel's `can_add_subscribers_group`, a member of that subgroup who thereby loses access must receive exactly two events, in order: the user-group `remove_subgroups` update event, then the channel-deletion event.
- **No access change, no extra events.** If a group-membership change does not alter a user's ability to see any channel (e.g. the affected channel is one the user can already see for another reason, or the group grants no additional visibility), that user must receive only the normal user-group update event — no channel create/delete events.

The same delta computation must apply to the metadata-access side of `do_change_stream_group_based_setting`: users gaining metadata access through a setting change get a channel-creation event rather than only a channel-permissions-change event, and users losing it get a channel-deletion event.

### No-op inputs

The bulk group-modification functions must be true no-ops for empty inputs — performing no database queries and sending no events. This already holds for `bulk_add_members_to_user_groups`, `bulk_remove_members_from_user_groups`, and `add_subgroups_to_user_group` with empty member/subgroup lists; `remove_subgroups_from_user_group` called with an empty subgroup list must behave the same way.

## Implementation notes

Computing "which users' access changed" is the hard part. Expect to share calculations or patterns with the existing `bulk_add_subscriptions` logic for computing access deltas. Be careful about query efficiency: these are bulk operations (e.g. creating a new user adds them to several groups at once), so avoid per-user or per-channel queries inside loops where a bulk computation is possible.
