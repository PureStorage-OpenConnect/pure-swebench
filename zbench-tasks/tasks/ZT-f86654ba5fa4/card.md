# ZT-f86654ba5fa4 -- slack_import: Ask importer for default email address visibility.

- lang: py   issue: #34982   tier: B
- fix: https://github.com/zulip/zulip/commit/f86654ba5fa42b0f199e779cd264c2ff7f45102e
- f2p: zerver.tests.test_slack_importer.SlackImporter.test_end_to_end_slack_import
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real feature work in the Slack import flow with an outcome-based hidden test: it posts the registration form with an email_address_visibility value, then asserts the imported (non-bot) users end up with that visibility while bots retain EVERYONE, plus the metadata is persisted. These are deterministic attribute assertions that fail before the change and pass after, with no exact-string snapshots, version gating, or format pinning."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The realm registration/confirmation endpoint accepts a new optional integer form field `email_address_visibility` (JSON-encoded int, one of the valid RealmUserDefault EMAIL_ADDRESS_VISIBILITY values) when the user starts a Slack import, letting the importing user choose the email address visibility applied to imported users.",
    "The selected value is persisted on the PreregistrationRealm's `data_import_metadata` JSON field under the key `email_address_visibility` before the deferred import job is queued.",
    "The module `zerver.actions.create_realm` exposes a function `get_email_address_visibility_default(org_type)` returning the default email-address-visibility for a realm of the given org type; for ordinary org types it returns `UserProfile.EMAIL_ADDRESS_VISIBILITY_ADMINS`. This default is used when no visibility was selected by the importing user.",
    "When the Slack import completes, every non-bot user in the imported realm has `email_address_visibility` set to the importer-selected value (falling back to the org-type default), and the realm's RealmUserDefault is set to the same value; bot users are unaffected and keep `EMAIL_ADDRESS_VISIBILITY_EVERYONE`."
  ],
  "reason": "The test's only new bindings are an API request field, the metadata key it is stored under (mirroring the field name, on the pre-existing data_import_metadata dict), and get_email_address_visibility_default(org_type) in zerver.actions.create_realm. I verified via git history that the helper is new in this fix's PR (#36259, commit 4bd9bb1995), but it is a cross-module function consumed by three modules and asserts product-level policy (org-type default = ADMINS), so a design brief could legitimately dictate its name, module, and signature. All other assertions go through pre-existing interfaces (do_create_user, UserProfile constants, user-visible import flow) or user-visible outcomes. Handed these four requirements, a solver is graded on correctness, not name-guessing."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_slack_importer.SlackImporter.test_end_to_end_slack_import"
  ],
  "reason": "All non-import hunks modify one contiguous test flow (the start_slack_import POST, is_import_work_queued assertion, and need_select_realm_owner check), which the upstream file places inside SlackImporter.test_end_to_end_slack_import \u2014 the only test class in test_slack_importer.py. The remaining hunk just adds imports (get_email_address_visibility_default, do_create_user) used by that method."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the UI/product intent (ask the importer for the org's default email visibility during Slack import), and the evidence plus interface requirements pin down the observable contract: the form field name and type, the data_import_metadata persistence key, the get_email_address_visibility_default(org_type) helper and its admins-only default for ordinary org types, and the post-import state (non-bot users and RealmUserDefault get the chosen value; bots keep EVERYONE). This is determinate and checkable, so two engineers would build compatible implementations."
}
