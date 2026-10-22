# Automatically scrub deactivated realms whose scheduled deletion date has passed

## Background

Zulip already supports scheduling deactivated realms for eventual data deletion. When a realm is deactivated with a deletion delay, its `scheduled_deletion_date` field is set. The module `zerver/actions/realm_settings.py` contains a per-realm routine, `scrub_deactivated_realm(realm)`, which checks whether a given realm is deactivated and past its scheduled deletion date, and if so scrubs its data by calling `do_scrub_realm(realm, acting_user=None)` (with logging). Reactivating a realm (`do_reactivate_realm`) clears its `scheduled_deletion_date`, cancelling the pending deletion.

What is missing is any automation that actually finds realms that are due for deletion and scrubs them. Nothing currently invokes `scrub_deactivated_realm` on a schedule, so realms past their deletion date sit untouched until an operator runs something by hand.

## Required behavior

Add batch cleanup logic that runs as part of the server's existing nightly offline maintenance, so that due realms get scrubbed automatically.

1. Add a new function `clean_deactivated_realm_data()` to `zerver/actions/realm_settings.py`. It takes no arguments. When called, it must:
   - Query for every realm that is **deactivated** (`deactivated=True`) **and** has a non-null `scheduled_deletion_date` that is at or before the current time.
   - For each such realm, perform the scrub through the existing per-realm path, i.e. `scrub_deactivated_realm`, so that each due realm ends up scrubbed exactly once via `do_scrub_realm(realm, acting_user=None)`.
   - Emit INFO-level logging when it scrubs a realm (the existing per-realm routine's logging satisfies this if the call goes through it).

2. Realms must **not** be scrubbed if any of the following hold:
   - The realm is not deactivated.
   - The realm has no `scheduled_deletion_date` (e.g. it was deactivated without scheduling deletion, or it was reactivated, which clears the field).
   - The realm's `scheduled_deletion_date` is still in the future.

   Concretely: if `clean_deactivated_realm_data()` is called when no realm's deletion date has arrived, `do_scrub_realm` must not be invoked at all. If it is called later, after one realm's date has passed but another realm was reactivated in the meantime, only the still-deactivated, past-due realm is scrubbed.

3. Wire this into the nightly cron job: the `archive_messages` management command (`zerver/management/commands/archive_messages.py`) must call `clean_deactivated_realm_data()` after its existing archiving/cleanup steps. Do not route this work through the deferred-work queue processor — the management command already runs in an offline job context, so a direct function call is the right mechanism.

## Interface requirements

- A no-argument function `clean_deactivated_realm_data()` must be importable from `zerver.actions.realm_settings`. It selects every realm that is deactivated and whose `scheduled_deletion_date` is at or before the current time, and scrubs each one.
- For each qualifying realm, the scrub must go through the pre-existing `scrub_deactivated_realm` routine in `zerver.actions.realm_settings`, resulting in exactly one `do_scrub_realm(realm, acting_user=None)` call per due realm. Realms that are not deactivated, whose deletion date has not yet arrived, or that were reactivated (clearing the scheduled deletion) must not be scrubbed.
- The `archive_messages` management command must additionally invoke `clean_deactivated_realm_data()` after its existing archiving steps.
