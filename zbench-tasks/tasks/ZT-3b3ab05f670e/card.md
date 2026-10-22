# ZT-3b3ab05f670e -- cron: Add cron job logic to delete fully deactivated realms.

- lang: py   issue: #32763   tier: B
- fix: https://github.com/zulip/zulip/commit/3b3ab05f670e0f2f45237b6cb5b6a587fa5e1295
- f2p: zerver.tests.test_realm.RealmTest.test_scrub_deactivated_realms
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real engineering task: add a periodic cleanup function that scrubs deactivated realms past their scheduled_deletion_date and wire it into the existing archive_messages cron command. The hidden test grades observable behavior deterministically \u2014 it calls clean_deactivated_realm_data() and asserts via mock which realms get scrubbed before/after the deletion date (using time_machine for controlled time travel), so it fails before the change and passes after. No snapshot pinning, no exact-string assertions, no version/wall-clock gating."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "A new no-argument function `clean_deactivated_realm_data()` is added to the module `zerver.actions.realm_settings` (importable from there): it selects every realm that is deactivated AND whose `scheduled_deletion_date` is at or before the current time, and scrubs each such realm.",
    "For each qualifying realm, `clean_deactivated_realm_data()` must perform the scrub through the existing per-realm scrub routine in `zerver.actions.realm_settings` (the pre-existing `scrub_deactivated_realm` path), so that each due realm is scrubbed exactly once via `do_scrub_realm(realm, acting_user=None)`; realms that are not deactivated, whose deletion date has not yet arrived, or that were reactivated (which clears the scheduled deletion) must not be scrubbed.",
    "The `archive_messages` management command additionally invokes `clean_deactivated_realm_data()` after its existing archiving steps (not directly asserted by the test shown, but part of the same product requirement)."
  ],
  "reason": "The test's only NEW binding is the function name `clean_deactivated_realm_data` and its location/signature (no-arg function in zerver.actions.realm_settings) \u2014 exactly the kind of public entry point a ticket would dictate ('add a cron-invoked function that scrubs all overdue deactivated realms'). Every other surface the test touches pre-exists at the base commit: `scrub_deactivated_realm`, the mock target `zerver.actions.realm_settings.do_scrub_realm` and its (realm, acting_user=None) call signature, the `scheduled_deletion_date` semantics, `do_reactivate_realm`, and the INFO-level scrub logging were all already exercised by the original version of this same test. The behavioral assertions (only realms past their scheduled deletion date get scrubbed; reactivated realms are excluded; each due realm scrubbed exactly once) are product semantics, not implementation guesses. Given the contract above in a brief, the test grades correctness rather than name-guessing, so this is specifiable rather than clean (new name) or coupled (no private internals are invented by the fix and pinned by the test)."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_realm.RealmTest.test_scrub_deactivated_realms"
  ],
  "reason": "The diff's import changes and both edited hunks (swapping scrub_deactivated_realm calls for clean_deactivated_realm_data and adding do_reactivate_realm(lear)) all fall within the body of RealmTest.test_scrub_deactivated_realms in zerver/tests/test_realm.py; no other test method is added or modified. Verified against the upstream file, where that method contains the clean_deactivated_realm_data() call sites."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the goal and design (batch function in zerver/actions/realm_settings called from archive_messages, iterating realms past their deletion date and calling scrub_deactivated_realm with logging), and the evidence pins down the exact function name, no-argument signature, selection criteria (deactivated AND scheduled_deletion_date <= now), the do_scrub_realm(realm, acting_user=None) delegation, INFO logging, and the reactivation-clears-deletion exclusion. Together these give a determinate, independently checkable outcome."
}
