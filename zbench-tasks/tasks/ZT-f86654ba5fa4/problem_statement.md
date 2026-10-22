# Make email-address visibility configurable in the Slack import flow

## Background

Zulip supports importing an organization from a Slack export. The import is kicked off from the "Import from Slack" page: after uploading the export, the importing user confirms via the realm registration/confirmation endpoint (the same `POST` that handles the confirmation `key`), passing `start_slack_import=true`. That request queues a `deferred_work` job which performs the actual data import into a newly created realm, using state stored on the `PreregistrationRealm` row's `data_import_metadata` JSON field (e.g. `uploaded_import_file_name`, `is_import_work_queued`, and later `need_select_realm_owner`).

Currently, the importing user has no control over how visible the imported users' email addresses will be in the new organization. This can surprise organizations: users' email addresses may end up visible to people the organization would not want to expose them to.

## Required behavior

During the Slack import flow, the importing user must be explicitly asked what the organization's default email-address visibility should be, and that choice must be applied to the imported users.

### UI

At the bottom of the "Import from Slack" page, add a setting:

- Label: **"By default, who will be allowed to see other users' email addresses?"**, with accompanying help text noting that users can configure email visibility for their own account.
- Control: a dropdown offering the same email-address-visibility choices shown in the personal configuration step when a user activates their own account (the standard `EMAIL_ADDRESS_VISIBILITY_*` options: everyone / members / admins / moderators / nobody, as applicable).

### Endpoint

The realm registration/confirmation endpoint accepts a new **optional** integer form field `email_address_visibility` (a JSON-encoded int that must be one of the valid `RealmUserDefault` email-address-visibility values) when the request starts a Slack import (`start_slack_import`). Invalid values should be rejected as a bad request.

When provided, the selected value must be persisted on the `PreregistrationRealm`'s `data_import_metadata` JSON field under the key `email_address_visibility` **before** the deferred import job is queued, so the import worker can read it.

### Default when no value is selected

The module `zerver.actions.create_realm` must expose a function `get_email_address_visibility_default(org_type)` that returns the default email-address visibility for a realm of the given organization type. For ordinary organization types it returns `UserProfile.EMAIL_ADDRESS_VISIBILITY_ADMINS`. This function supplies the value used when the importing user did not select one, and should also be the source of the default applied when realms are created normally (i.e., a freshly created realm's human users default to admins-only email visibility for ordinary org types).

### Applying the setting during import

When the deferred Slack import job completes:

- Every **non-bot** user profile in the imported realm must have its `email_address_visibility` set to the importer-selected value from `data_import_metadata["email_address_visibility"]`, falling back to `get_email_address_visibility_default(org_type)` if no value was stored.
- The imported realm's `RealmUserDefault` row must have its `email_address_visibility` set to that same value, so future users joining the organization get the same default.
- **Bot** users must not be affected by this setting: they keep `UserProfile.EMAIL_ADDRESS_VISIBILITY_EVERYONE`.

For example, if the importing user selects "Nobody" (`EMAIL_ADDRESS_VISIBILITY_NOBODY`) when starting the import, then after the import finishes every imported human account has `email_address_visibility == EMAIL_ADDRESS_VISIBILITY_NOBODY`, while imported bots remain at `EMAIL_ADDRESS_VISIBILITY_EVERYONE`.

## Interface requirements

- The realm registration/confirmation endpoint accepts a new optional integer form field `email_address_visibility` (JSON-encoded int, one of the valid `RealmUserDefault` `EMAIL_ADDRESS_VISIBILITY` values) when the user starts a Slack import, letting the importing user choose the email-address visibility applied to imported users.
- The selected value is persisted on the `PreregistrationRealm`'s `data_import_metadata` JSON field under the key `email_address_visibility` before the deferred import job is queued.
- The module `zerver.actions.create_realm` exposes a function `get_email_address_visibility_default(org_type)` returning the default email-address visibility for a realm of the given org type; for ordinary org types it returns `UserProfile.EMAIL_ADDRESS_VISIBILITY_ADMINS`. This default is used when no visibility was selected by the importing user.
- When the Slack import completes, every non-bot user in the imported realm has `email_address_visibility` set to the importer-selected value (falling back to the org-type default), and the realm's `RealmUserDefault` is set to the same value; bot users are unaffected and keep `EMAIL_ADDRESS_VISIBILITY_EVERYONE`.
