# Migrate web-app draft data structures to store DM recipients as user IDs instead of API emails

## Background

In the Zulip web app, message drafts are persisted in browser `localStorage` (see `web/src/drafts.ts` and related modules). For direct-message (private) drafts, the stored draft object currently carries a legacy field `private_message_recipient`: a comma-separated string of the recipients' API email addresses (e.g. `"iago@zulip.com,zoe@zulip.com"`). Whenever the app needs to operate on these recipients (restoring a draft into the compose box, rendering the drafts overlay, filtering/sorting drafts, etc.), it converts these email strings to user IDs on the fly.

Storing emails is fragile — emails can change, while user IDs are stable — and the rest of the web app has largely moved to user-ID-based data models. The drafts subsystem should do the same.

## Required behavior

### 1. New persisted draft format

- Direct-message drafts stored in `localStorage` must use a new field `private_message_recipient_ids: number[]` — an array of recipient user IDs, in recipient order — instead of the legacy `private_message_recipient` email string.
- All code paths that create or update DM drafts (saving from the compose box, restoring drafts, drafts-overlay rendering, draft filtering, narrow matching, etc.) must read and write `private_message_recipient_ids`.
- A DM draft with no recipients must store an empty array `[]` (not an empty string or a missing field), and all consumers must handle that case (e.g. the drafts overlay should still render such a draft, showing an empty recipient list).
- The TypeScript draft schema/types must reflect the new field.

### 2. Migration of historical drafts

Users have existing drafts saved in the legacy format, and these must not be lost or broken.

- When drafts are loaded from `localStorage`, any DM draft that still has the legacy `private_message_recipient` field (a comma-separated email string) must be migrated in place, as part of the existing draft fixing/normalization pass that runs when reading drafts:
  - The email string is parsed and each email is resolved to its user ID via the people module; the resulting IDs are stored in `private_message_recipient_ids`, preserving the original recipient order.
  - The legacy `private_message_recipient` field is deleted from the stored draft, so that after migration, reading that draft yields `private_message_recipient` as `undefined` and `private_message_recipient_ids` as the resolved ID array.
- After migration, the draft must behave identically to a natively new-format draft (retrievable by its original draft ID, editable, restorable into compose).

### 3. Supporting changes in the people module (`web/src/people.ts`)

Because draft consumers now hold user IDs rather than emails, the people module needs user-ID analogs of some email-based helpers.

- New exported function `is_valid_user_id_for_compose(user_id: number): boolean` — the user-ID analog of the existing `is_valid_email_for_compose`. It must return `true` for user IDs belonging to active users, non-active (deactivated) users, and cross-realm bots; it must return `false` for unknown user IDs.
- The exported function `emails_to_full_names_string(emails)` is replaced by `user_ids_to_full_names_string(user_ids: number[]): string`. It resolves each user ID to a full name (using the translated string `"Unknown user"`, passed through the i18n translation layer, for any ID that cannot be resolved to a known user), and returns those names **sorted alphabetically (case-insensitive) by full name**, joined by `", "`. This alphabetical sort preserves the prior `emails_to_full_names_string` behavior; the output is NOT in recipient/input order. All callers of the old email-based function must be updated to pass user IDs.
- New exported function `sort_user_ids_by_username(user_ids: number[]): number[]` — returns the given user IDs sorted alphabetically (case-insensitive) by their resolved full name (an unresolved ID sorts under `"Unknown user"`).
- When either of these functions encounters an unknown user ID, the lookup must go through the existing user lookup helper that logs the error `"Unknown user_id in maybe_get_user_by_id"` (this helper and its error message already exist in the codebase). Unknown IDs must trigger that error log rather than being silently skipped; the functions still return their normal results as described above (i.e. `false`, or a name list containing "Unknown user").

## Interface requirements

- Persisted DM drafts use `private_message_recipient_ids: number[]` (user IDs, recipient order preserved) in place of the legacy `private_message_recipient` comma-separated email string; an empty recipient list is stored as `[]`.
- On load, legacy DM drafts carrying `private_message_recipient` are migrated in place: emails are resolved to user IDs stored in `private_message_recipient_ids` (order preserved), and the legacy field is removed so it reads back as `undefined`.
- `web/src/people.ts` exports `is_valid_user_id_for_compose(user_id: number): boolean`, returning `true` for active users, deactivated users, and cross-realm bots, and `false` for unknown user IDs.
- `web/src/people.ts`'s exported `emails_to_full_names_string(emails)` is replaced by `user_ids_to_full_names_string(user_ids: number[]): string`, returning full names **sorted alphabetically (case-insensitive) by full name** and joined by `", "`, with unknown user IDs contributing the translated string `"Unknown user"`. (The alphabetical sort matches the prior behavior; the output is not in recipient order.)
- `web/src/people.ts` exports `sort_user_ids_by_username(user_ids: number[]): number[]`, returning the user IDs sorted alphabetically (case-insensitive) by resolved full name.
- Resolving an unknown user ID in these functions routes through the existing lookup that logs the error `"Unknown user_id in maybe_get_user_by_id"`, so unknown IDs produce that error log instead of being silently ignored.

## Constraints and notes

- Do not change the server API or the format of data sent to the server; this migration concerns only the web app's client-side draft storage and in-memory data structures.
- Update all web-app call sites that produced or consumed the legacy `private_message_recipient` draft field (compose save/restore, drafts overlay formatting, draft filtering and search, narrow/message-matching logic) so the codebase consistently uses `private_message_recipient_ids`.
- Recipient order matters for the STORED data: migration and any email→ID conversion must preserve the order in which recipients appear in `private_message_recipient_ids`. (Exception: the display helper `user_ids_to_full_names_string` returns names sorted alphabetically, as specified above — it does not preserve recipient order.)
