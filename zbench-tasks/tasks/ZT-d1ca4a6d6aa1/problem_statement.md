# Live-update UI when a user is deactivated or reactivated

## Background

In the Zulip web app, when an administrator deactivates a user, other clients learn about it via a realm-user update event carrying the user's new `is_active` value. This event is processed on the client in `web/src/user_events.ts` (`update_person`).

## Current behavior (bug)

When a user is deactivated (or reactivated) while another client is running, several parts of the UI do not live-update to reflect the user's new deactivated/active status:

- **The left sidebar direct-messages list** (`pm_list`): if you have a DM conversation with the affected user visible in the left sidebar, its rendering does not refresh, so the user's deactivated state is not shown.
- **The compose box recipient pill** (`compose_pm_pill`): if you are composing a DM and the affected user is already a recipient pill in the compose box, the pill does not update to indicate the user is deactivated.

Because of this, a user can start (or continue) composing a message to a now-deactivated user without any visual indication, and only discover the problem when the send fails. The stale state persists until a reload.

## Required behavior

Whenever the client processes a user-update event that changes a person's `is_active` field — deactivation **or** reactivation, and for **both** human users and bots — the following UI must be refreshed as part of handling that event:

1. **Left sidebar DM list**: the direct-messages list rendering must be refreshed (via the existing `pm_list.update_private_messages()` mechanism) so any DM rows involving the affected user reflect their new deactivated/active status.
2. **Compose recipient pills**: if the compose box currently contains a recipient pill for the affected user, that pill must be updated in place to reflect the user's new status — e.g. showing the "deactivated" styling/indicator when the user is deactivated, and removing it when the user is reactivated. If the user is not currently a pill recipient, this is a no-op; it must not throw or otherwise disturb the compose state.

All pre-existing handling of `is_active` changes (updating the people data layer so `people.is_person_active()` reflects the new value, buddy list updates, bot-settings updates for bots, etc.) must continue to work unchanged.

## Interface requirements

- The module `web/src/compose_pm_pill` must expose a new exported function `update_user_pill_active_status(user, is_active)`. It takes the affected user object (including its `user_id`) and a boolean `is_active`, and updates the compose box's recipient pill for that user (if present) to reflect whether the user is deactivated or active.
- When `user_events.update_person` processes a user-update event whose `is_active` field changes (deactivation or reactivation, for both human users and bots), it must call `compose_pm_pill.update_user_pill_active_status(user, is_active)`, passing the affected user's full user object and the new active status.
- In the same situation, it must also refresh the direct-messages list by calling the existing `pm_list.update_private_messages()`.

## Notes for implementation

- The `is_active` handling in `update_person` already has branches for humans vs. bots; the two UI refresh calls above must fire in every case where `is_active` changes, regardless of whether the affected person is a human or a bot, and regardless of the direction of the change (false→true or true→false).
- The user object passed to `update_user_pill_active_status` should be the person record for the affected user (the same object used elsewhere in the event handler), not just a user ID.
