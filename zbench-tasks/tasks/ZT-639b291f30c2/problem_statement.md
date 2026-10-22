# Realm import fails with spurious "Export was generated on a different Zulip version" error when migration lists are identically populated but differently ordered

## Context

Zulip's realm export (`zerver/lib/export.py`) writes a `migrations_status.json` file into the export directory recording, for each Django app, the list of migrations applied on the exporting server (collected via `get_migrations_by_app`). When that export is later imported with `manage.py import`, the import path (`zerver/lib/import_realm.py`, in its migration-status check invoked by `do_import_realm`) collects the same information for the local server and compares it against the exported file. If the check decides the two servers' database formats differ, the import aborts with an error like:

```
Error: Export was generated on a different Zulip version.
Export version: 10.0-dev-2143-gd3df54f54c
Server version: 10.0-dev-2278-g3eb501fa18

Database formats differ between the exported realm and this server.
Printing migrations that differ between the versions:
```

followed by a per-app diff of the migration lists.

## Current (buggy) behavior

The comparison between the exported migration lists and the local server's migration lists is order-sensitive. The order in which applied migrations are recorded is not stable across servers (the database does not guarantee a return order, and squashed/renumbered migrations can legitimately be applied in different sequences), so two servers whose *sets* of applied migrations are exactly identical for every app can still fail the check purely because the lists are ordered differently.

This produces confusing failures in practice. For example, importing a Zulip Cloud export into a self-hosted server on an equivalent version aborts, and the printed diff shows the same migration names appearing as both added and removed lines — i.e., pure reordering noise, not a real schema difference:

```
'social_auth' app:
-0005_auto_20160727_2333
 0001_initial
+0002_add_related_name
 0003_alter_email_max_length
 0004_auto_20160423_0400
-0002_add_related_name
+0005_auto_20160727_2333
```

Here both sides have applied exactly the same five `social_auth` migrations, yet the import is rejected.

## Required behavior

1. The import-time migration-status check must treat the exported and local migration data as equal whenever, for every app, the two sides have the same set of applied migrations — regardless of the order in which the migration names appear in `migrations_status.json` or in the locally collected data. In that case the import must proceed normally with no version-mismatch error, exactly as it would if the lists had been in identical order.
2. Concretely: given an export whose `migrations_status.json` lists the same migrations per app as the importing server but in shuffled/unsorted order (e.g., an `auth` entry listed as `["0004_...", "0003_...", "0002_...", "0001_initial"]` while the server records them ascending), `do_import_realm` must complete successfully.
3. When the migration sets genuinely differ (a migration present on one side and absent on the other), the check must still abort the import with the existing error message, and the printed per-app diff should reflect only real differences — it should not contain lines that are mere reordering artifacts.
4. The behavior must be robust regardless of which side produced unordered data: an export generated with unordered lists imported into a server that enumerates them in order (or vice versa) must be handled the same way. Normalizing the ordering consistently at both the export/collection side and the comparison side is acceptable, as long as previously generated exports with unsorted lists still import successfully against an identical server.

## Notes for implementation

- Both the export and import code paths obtain per-app applied-migration lists through a shared helper (`get_migrations_by_app`); the fix should ensure the comparison is insensitive to list order however the data was produced.
- Do not change the on-disk file name (`migrations_status.json`) or its overall structure (a JSON object mapping app label to a list of migration names).
- Unrelated warnings (e.g., about apps like `guardian` or `sites` installed on only one side) and the genuine-mismatch error path must keep working as before.
