# ZT-639b291f30c2 -- import: Sort realms migrations status before checking.

- lang: py   issue: #32826   tier: B
- fix: https://github.com/zulip/zulip/commit/639b291f30c2a96bbceab9481a581d43063a7bc7
- f2p: zerver.tests.test_import_export.RealmImportExportTest.test_import_realm_with_identical_but_unsorted_migrations
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real bug fix in a genuine workflow (realm import fails on order-only migration list differences). The hidden test grades observable behavior deterministically: it feeds identical-but-unsorted migration lists via fixtures and asserts the import completes rather than raising, which fails before the fix and passes after. No exact-string/snapshot pinning, no version/time gating, no migration-internals assertions \u2014 the fixture is just controlled input, not a brittle expected output."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test introduces no new names from the fix. Every symbol it binds to exists at the base commit: `get_migrations_by_app` (in both zerver.lib.export and zerver.lib.import_realm namespaces, which the code diff does not add or rename \u2014 it only changes the comparison logic inside the pre-existing `check_migration_status`), the fixture helper `get_applied_migrations_fixture`, the existing `with_complete_migrations.json` fixture, `export_realm_and_create_auditlog`, `do_import_realm`, `get_output_dir`, and `RealmExport.EXPORT_FULL_WITH_CONSENT`. The new fixture file is test-owned data added to an already-existing fixtures directory, not a name the solution must produce. The assertion is purely behavioral and user-visible: exporting and importing a realm whose applied-migrations lists are set-identical but differently ordered must succeed instead of raising a mismatch error. Any correct fix to the order-sensitive comparison in `check_migration_status` passes; no author-private naming or internal structure invented by the fix is required."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue plus the expected-behavior evidence make the outcome determinate: the migration-status comparison during realm import currently fails on identically populated but differently ordered migration lists (visible in the issue's diff output where the same names appear as both + and - lines), and the required behavior is that such imports succeed while genuinely differing migration sets still abort. The relevant code locations (export/import migration-status check, migrations_status.json, get_migrations_by_app) are identifiable from the issue text and codebase alone."
}
