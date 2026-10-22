# ZT-2cbf9e130e35 -- drafts: Store DM drafts with user ids instead of emails.

- lang: web   issue: #34468   tier: B
- fix: https://github.com/zulip/zulip/commit/2cbf9e130e35ef742ba8a0225925ae29184d81d6
- f2p: web/tests/drafts.test.cjs, web/tests/people.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior-affecting refactor / data-format migration",
  "reason": "This changes observable web-client behavior: DM drafts are stored with user IDs, legacy email-based drafts in localStorage are converted on load (old field deleted, new IDs populated), invalid-recipient filtering and draft-to-narrow matching move to ID-based logic, and new people.ts helpers (is_valid_user_id_for_compose, user_ids_to_full_names_string, sort_user_ids_by_username) are introduced. The hidden tests grade deterministic outcomes \u2014 e.g. a stored draft with private_message_recipient emails is asserted to come back with private_message_recipient undefined and private_message_recipient_ids equal to the correct IDs, plus targeted assertions on the new helpers \u2014 not exact rendered snapshots or incidental formatting (templates are stubbed). Fails before the change, passes after; a realistic assigned engineering task."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The persisted (localStorage) draft format for direct-message drafts replaces the legacy `private_message_recipient` comma-separated email string with a new field `private_message_recipient_ids: number[]` holding the recipients' user IDs; an empty recipient list is stored as `[]` (not an empty string).",
    "On loading drafts, legacy direct-message drafts that still carry `private_message_recipient` (emails) must be migrated in place: the email string is resolved to user IDs stored in `private_message_recipient_ids` (preserving recipient order), and the legacy `private_message_recipient` field is removed so it reads back as undefined.",
    "The people module gains an exported function `is_valid_user_id_for_compose(user_id: number): boolean`, the user-ID analog of the existing `is_valid_email_for_compose`: it returns true for active users, non-active (deactivated) users, and cross-realm bots, and false for unknown user IDs.",
    "The people module's exported `emails_to_full_names_string(emails)` is replaced by `user_ids_to_full_names_string(user_ids: number[]): string`, which returns the users' full names joined by ', '; any unknown user ID contributes the translated string 'Unknown user' in its position.",
    "Resolving an unknown user ID (e.g. in `user_ids_to_full_names_string` or `is_valid_user_id_for_compose`) must route through the existing lookup that logs the error message 'Unknown user_id in maybe_get_user_by_id' (this message and lookup already exist at the base commit); unknown IDs must produce that error log rather than being silently ignored."
  ],
  "reason": "The test binds only to new contract surface a migration ticket would naturally pin: the new persisted draft field name `private_message_recipient_ids` and its migration semantics (legacy email field removed, IDs populated, [] sentinel for no recipients), plus two exported people-module functions (`is_valid_user_id_for_compose`, `user_ids_to_full_names_string`) that are direct ID-based analogs of pre-existing exported email-based APIs, with user-visible 'Unknown user' fallback text. The `blueslip.expect` assertions pin an operator-facing error message, but that exact string pre-exists at the base commit in `maybe_get_user_by_id`, so a brief stating that unknown IDs log via the existing lookup fully specifies it. Remaining assertions (getDraft, format_drafts template data, filter_drafts behavior) go through pre-existing interfaces and observable outcomes. No private helpers, internal mock targets, or invented module layout are asserted, so a solver handed these requirements would be graded on correctness, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the goal (store user IDs, not emails, with a safe migration for historical drafts), and the evidence plus interface requirements pin down the concrete observable contract: the new field name and type, empty-list representation, in-place migration semantics (legacy field removed, order preserved), and the exact people-module API changes including error-logging behavior for unknown IDs. This is determinate and checkable by an engineer with only the codebase."
}
