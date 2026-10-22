# Improve the data export flow when some users' email addresses are not accessible

## Context

Zulip organization administrators can start data exports from **Organization settings → Data exports**. When an administrator starts a **standard export** (the export type that includes private data), each user's email address is only included in the export if the acting administrator can access that user's real (delivery) email address. Users may configure their email address visibility so that administrators cannot see their real email; in the web client, such users have no accessible delivery email. Anyone whose email address is missing from an export will be unable to log in if that export is later imported into a new Zulip organization.

## Current behavior

When a user starts a standard export and **none of the organization owners** would have their email address included in the export, the web client shows an error and refuses to start the export. This hard block is undesirable: the export itself is still valid and useful, and the missing emails are only a problem for logging in after a re-import.

Additionally, the confirmation modal shown before starting a standard export gives no information about which or how many users would be unable to log in after importing the exported data.

## Required behavior

1. **Remove the blocking error.** A standard export must be startable even when no organization owner has an exportable email address. There should no longer be any code path that prevents the export from running because of inaccessible email addresses.

2. **Add an informational note to the standard-export confirmation modal.** Let *N* be the number of users whose email addresses will not be included in the export (i.e., users whose real email the acting user cannot access or export). If *N* > 0, append the following note at the end of the confirmation modal:

   > If you import the data into a new Zulip organization, {N} users will be unable to log in. Their email addresses will not be included in the export because you don't have permission to [access](/help/configure-email-visibility) or export their emails.

   The word "access" must link to the `/help/configure-email-visibility` help page. The string must be translatable and correctly handle pluralization of the user count.

3. **Call out affected owners and administrators by name.** If any of the users counted in *N* are organization owners or organization administrators (i.e., people who would normally be expected to be able to log in and administer a newly imported organization), additionally show:

   > The following administrators will be unable to log in: {name1}, {name2}, …

   listing the full names of the affected owners and administrators. Rendering these names as user pills (the standard user-pill widget) is a nice-to-have, not a hard requirement; a plain comma-separated list of names is acceptable.

4. If every user's email address will be included in the export (*N* = 0), the confirmation modal must look as it does today, with no extra note.

## Interface requirements

- `web/src/people.ts` must export a new function `get_users_that_match_role_ids(user_ids: Set<number>, role_ids: Set<number>): User[]` — given a set of user IDs and a set of role codes, it returns the User objects (looked up among known users) whose `role` matches one of the given role codes; users whose role is not in the set (or who can't be resolved to a known user) are omitted.
- The role codes passed in are the pre-existing `settings_config.user_role_values.<role>.code` values (admin, owner, moderator, etc.) — the function filters on the user's existing `role` field against these codes; no new sentinel values are introduced.
- The order of the returned array is not part of the contract — callers must treat the result as an unordered collection, and any ordering of the matching users is acceptable.

The export-modal logic should use this function (passing the owner and admin role codes) to determine which of the users with inaccessible emails are owners or administrators for the second note.

## Behavioral examples for the new function

Given known users consisting of an owner, an admin, a moderator, and a guest, and `user_ids` containing all four of their IDs:

- With `role_ids = {admin code}`, the result contains exactly the admin user.
- With `role_ids = {moderator code}`, the result contains exactly the moderator user.
- With `role_ids = {admin code, owner code}`, the result contains exactly the owner and the admin, in any order.
