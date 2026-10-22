# Show "Muted user" instead of the real name in the DM narrow navbar title

## Context

Zulip lets a user mute other users. Throughout the web app UI, a user muted by the current user is generally displayed as "Muted user" rather than by their real name (for example in message lists and recipient rows). However, one place was missed: the navbar title shown at the top of a direct-message (DM) narrow.

## Current behavior

When the current user narrows to a DM conversation (a `dm` narrow, e.g. via `#narrow/dm/...`), the navbar title is built from the full names of the conversation's participants (other than the current user). This happens in the web client's narrow-title computation (the logic that produces a title for a set of narrow terms, in `web/src/filter.ts`). If one of those participants has been muted by the current user, their real full name still appears in the title. Examples:

- 1:1 DM with muted user "jeff" → title reads "jeff".
- Group DM with "joe" and muted user "jeff" → title reads "joe and jeff".

## Required behavior

In the navbar title of a DM narrow, every participant who has been muted by the current user must be shown as the translatable string **"Muted user"** in place of their full name. Whether a participant is muted is determined by the existing muted-users module (`web/src/muted_users.ts`). Specifically:

1. **1:1 DM with a muted user:** the title must be exactly the translated string "Muted user".
2. **Group DM including one or more muted users:** each muted participant's name is replaced by "Muted user" within the usual human-readable name list; unmuted participants keep their current rendering. E.g. a group DM with joe and a muted user renders as "joe and Muted user". The existing ordering of participants in the list must not change.
3. **Muted guest users:** Zulip appends a guest indicator to guest names in these titles when the realm setting to show guest indicators (`realm_enable_guest_user_indicator`) is on; normally a guest named alice renders as the translated form of "alice (guest)". For a *muted* guest, the title must instead use the single translatable string **"Muted user (guest)"** — i.e. the whole phrase is one translated string, not the muted-user placeholder substituted into the generic "{name} (guest)" template. This applies both in 1:1 DMs (title is exactly "Muted user (guest)") and inside group-DM name lists (e.g. "joe and Muted user (guest)"). When the guest-indicator realm setting is off, a muted guest renders simply as "Muted user".

Both "Muted user" and "Muted user (guest)" must go through the standard i18n translation mechanism used elsewhere in the web client.

## What must NOT change

- Only the displayed title text changes. The narrow's redirect/search URL must continue to use the participant's real user ID and name slug (e.g. `/#narrow/dm/34-jeff` for a 1:1 DM with muted user jeff, and the usual `/#narrow/dm/<id>,<id>-group` form for group DMs).
- The navbar icon for DM narrows, the "is common narrow" classification, and titles for DM narrows containing no muted participants (including the existing guest-indicator rendering for unmuted guests) must all remain as they are today.
- Behavior for other narrow types is unaffected.

## Interface requirements

- In the navbar title of a direct-message narrow, a participant who has been muted by the current user must be displayed as the literal (translatable) string "Muted user" instead of their full name.
- If the muted participant is a guest and the realm shows guest indicators, the displayed string must instead be "Muted user (guest)", replacing the usual "{name} (guest)" form.
