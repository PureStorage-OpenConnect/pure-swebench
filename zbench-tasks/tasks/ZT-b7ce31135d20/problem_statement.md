# Show deactivated users correctly in the right sidebar (buddy list)

## Background

Zulip's web app shows a "buddy list" in the right sidebar. Each user row has a small circle indicator whose CSS class reflects presence (e.g. `user-circle-active`, `user-circle-idle`, `user-circle-offline`), computed by `buddy_data.get_user_circle_class(user_id)`. Rows are sorted into levels by `buddy_data.level(user_id)`; users with no presence data sort at level 3 (offline). Elsewhere in the app (e.g. message headers for direct-message conversations), deactivated users are already marked with a slashed-circle/ban icon.

## Current behavior (problems)

1. When a user account is deactivated or reactivated (an `is_active` change arrives in `user_events.update_person`), the code path unconditionally removes the user from the buddy list via `buddy_list.maybe_remove_user_id`. This is wrong for contexts where the user should remain visible — in particular, when the current view is a direct-message conversation that includes that user, the participant should stay listed.
2. Deactivated users who do appear in the right sidebar (as participants of a DM conversation being viewed) are rendered with an ordinary presence circle, with no visual indication that the account is deactivated.

## Required behavior

1. **Deactivated indicator.** A deactivated user shown in the buddy list must have their user-circle indicator carry the CSS class `user-circle-deactivated`, and that indicator must render as a ban (slashed-circle) icon instead of a presence circle. This class must be applied regardless of the user's presence status — a deactivated user is never shown as active/idle/offline.
2. **Sorting unaffected.** Marking a user as deactivated must not change their sort position logic: `buddy_data.level(user_id)` must still return 3 (the offline level) for a user with no presence data, whether or not they are deactivated.
3. **Live update on (de)activation.** When a user is deactivated or reactivated, the right sidebar must update in place: the handler for `is_active` changes must update the user's row position rather than removing them. Whether the user actually appears is then governed by the normal display rules (deactivated users appear only when they are participants in the DM conversation currently in view; in all other contexts they are hidden).
4. **Counts.** User counts shown in the sidebar must match what is displayed: deactivated users count toward the "In this conversation" participant count for a DM view that includes them, and are excluded from counts everywhere else.

## Interface requirements

- `buddy_data.get_user_circle_class` gains an optional second boolean parameter (default `false`). When it is `true`, the function returns the CSS class `"user-circle-deactivated"` unconditionally, ignoring the user's presence status; when `false`/omitted, behavior is unchanged.
- Deactivated users shown in the buddy list carry the CSS class `user-circle-deactivated` on their user-circle indicator, rendered as a ban icon instead of a presence circle.
- A deactivated user's buddy-list sort level is unchanged by the deactivated indicator: `buddy_data.level` continues to return 3 (the offline level) for a user with no presence data, whether or not the user is deactivated.
- On the code path handling a change to a user's `is_active` status (deactivation or reactivation), the user must no longer be removed from the buddy list via `buddy_list.maybe_remove_user_id`; instead the row position must be updated by calling the existing `buddy_list.insert_or_move([user_id])`, and no other `buddy_list` module functions may be invoked on this path.

## Notes

- `insert_or_move` already handles deciding whether a row belongs in the list and where, so routing the `is_active` change through it both fixes the DM-participant case and keeps deactivated users hidden in other contexts.
- Follow the existing pattern used elsewhere in the codebase for rendering deactivated-user ban icons so styling stays consistent.
