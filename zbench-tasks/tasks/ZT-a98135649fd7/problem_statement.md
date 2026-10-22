# Show a "deactivated" indicator for deactivated users throughout the web app

## Background

In the Zulip web app, deactivated users (and deactivated bots) currently appear inconsistently: in most places they look just like active users, and in compose-box recipient pills they are marked with a "(deactivated)" text suffix. We want a consistent visual treatment: a "deactivated" icon — the same icon already used next to deactivated accounts in the organization settings users list — shown wherever a deactivated user or bot appears.

## Required behavior

Apply the same icon and placement rules for deactivated human users and deactivated bots:

1. **Places that show a presence dot** (left sidebar direct-message list and buddy list, user profile popovers/panels, and anywhere else a presence indicator appears): for a deactivated user, replace the presence dot with the deactivated icon. No presence circle should be rendered for a deactivated user.

2. **Message feed and user pills** (avatars): show the deactivated icon at the bottom-right corner of the avatar, when an avatar is displayed. The avatar and the user's name should be rendered faded (reduced opacity) to further signal the account is deactivated.

3. **Everywhere else** a deactivated user's name appears without an avatar or presence dot: show the deactivated icon immediately to the left of the name.

4. **Compose box recipient pills**: once the icon is shown on the pill, drop the "(deactivated)" text suffix from the pill — the icon replaces the text marker.

Active users must be completely unaffected: no icon, no fading, and existing presence indicators unchanged.

## Interface requirements

The implementation must expose the following, with exactly these names and semantics:

- The `people` module must export a new function `sender_is_deactivated(message): boolean`. It returns `true` if and only if the given message's sender is a deactivated user, and returns `false` when `message.sender_id` is missing or `undefined`. It should mirror the shape and behavior of the existing `sender_is_bot` and `sender_is_guest` helpers in the same module.

- Message-list rendering must determine each sender's deactivation status by calling `people.sender_is_deactivated(message)` and expose the result as a boolean field named `sender_is_deactivated` on the per-message template data (the MessageContainer object), alongside the existing `sender_is_bot` and `sender_is_guest` fields, so templates can fade the sender and place the icon.

- Each display object returned by `pm_list_data.get_conversations()` must gain a boolean field `is_deactivated`: `true` when the direct-message conversation is a 1:1 conversation with a deactivated user, and `false` otherwise — including for group DM conversations and for conversations with active bots. This lets the left-sidebar DM list swap the presence circle for the deactivated icon.

## Notes

- "Deactivated" here means the account's `is_active` flag is false (the same state that removes a user from `people`'s active-user set, e.g. after `people.deactivate(user)`).
- Reuse the existing deactivated-user icon from the organization settings users list rather than introducing a new asset.
- Keep the treatment identical for users and bots; do not special-case bots beyond what the placement rules above imply.
