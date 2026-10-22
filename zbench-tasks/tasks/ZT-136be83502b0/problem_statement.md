# Compose box: warn when mentioning a user group with no members subscribed to the channel

## Background

In the Zulip web app, when a user is composing a message to a channel and inserts an **@-mention of an individual user** who is not subscribed to that channel, the compose box shows a warning banner (see `warn_if_mentioning_unsubscribed_user` in `web/src/compose_validate.ts`), because the mentioned person will not be notified.

There is currently **no analogous warning for user-group mentions**. If someone mentions a user group (e.g. `@*support-team*`) in a channel where *none* of the group's members are subscribed, the mention silently notifies nobody, and the sender gets no indication of this.

## Required behavior

When a user selects a **user-group mention** from the compose typeahead while composing to a channel, and the mention is **not silent** (i.e. not the `_@` silent-mention form), the app must check whether any member of the group is subscribed to the channel the user is composing to. Group membership must be computed **recursively**: members of subgroups (at any depth) count as members of the group. Only **active** users count; deactivated users must be ignored.

If **no** active member of the group (including recursive subgroup members) is subscribed to the target channel, show a warning banner in the compose box area:

- **Text:** "None of the members of **{group}** are subscribed to this channel, so mentioning the group won't notify anyone." — where `{group}` is the group's name, rendered as a group pill/link within the banner.
- **Style:** yellow/warning-colored banner, consistent with the existing unsubscribed-user mention warning banner.
- **Buttons:** none (unlike the unsubscribed-user banner, there is no action button such as "Subscribe them"; the banner should still be dismissable the standard way warning banners are).

Clicking the group name/pill inside the banner must open the **group information popover** for that group.

The banner must **not** appear when:

- At least one active member of the group (direct or via subgroups) is subscribed to the channel.
- The mention is a **silent** mention.
- The compose target is a direct-message conversation rather than a channel.

Avoid stacking duplicate banners: mentioning the same group again should not add a second copy of the same warning. Existing behavior for individual-user mention warnings must be unchanged.

## Interface requirements

- `web/src/compose_validate.ts` must export a function `warn_if_mentioning_unsubscribed_group(mentioned_group, $textarea, is_silent)`, mirroring the existing `warn_if_mentioning_unsubscribed_user`. When a user selects a user-group mention from the compose typeahead into a channel compose box, the typeahead code path must call this function; for a non-silent mention it shows the warning banner described above if no active member of the group (including recursive subgroup members) is subscribed to that channel, and otherwise does nothing.
- `web/src/compose_validate.ts` must also export an `initialize()` function that registers the module's one-time UI event handlers — in particular the click handler that opens the group info popover from the warning banner's group pill. This `initialize()` must be called exactly once during application startup, in the same place the other compose-related modules' `initialize()` functions are invoked (the web app's main startup sequence).

## Notes for implementation compatibility

- Follow the existing pattern used for the unsubscribed-user mention warning (banner component, warning classnames, and how `warn_if_mentioning_unsubscribed_user` is wired into the compose typeahead selection handler), so the new banner behaves consistently with the existing one.
- The banner text above is user-facing copy and should be translatable, matching how other compose banners handle translation, with the group name substituted in.
