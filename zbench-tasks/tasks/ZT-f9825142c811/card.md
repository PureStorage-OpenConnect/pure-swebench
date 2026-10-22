# ZT-f9825142c811 -- settings: Add frontend to change allow_edit_history to integer field.

- lang: web   issue: #21398   tier: B
- fix: https://github.com/zulip/zulip/commit/f9825142c811cf28c04ad3c148ad2f91893e6579
- f2p: web/tests/message_events.test.cjs, web/tests/popover_menus_data.test.cjs, web/tests/settings_org.test.cjs
- p2p: web/tests/hotkey.test.cjs, web/tests/message_view.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real settings feature: replaces the boolean realm_allow_edit_history with an integer message_edit_history_visibility_policy enum, changing observable client behavior (edit-history local echo now gated on 'always' vs move-only policies, history viewer gating, settings widget becomes a dropdown). The hidden tests exercise behavior deterministically \u2014 overriding the new realm policy field and asserting outcomes like discard-changes restoring the dropdown value and edit-history side effects \u2014 rather than pinning long strings, snapshots, feature levels, or migration internals. This is a plausible assigned engineering task and fails-before/passes-after cleanly."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "the realm object gains an integer-enum setting `realm_message_edit_history_visibility_policy`, replacing the boolean `realm_allow_edit_history`",
    "the frontend module `settings_config` exports `message_edit_history_visibility_policy_values`, an object with (at least) keys `always` and `never`, each entry having a numeric `code` property holding the API enum value for that policy (tests reference codes only via this object, so exact numbers are not asserted)",
    "semantics: policy code `never` means message edit history is not visible (edit-history UI suppressed, no client-side edit_history bookkeeping); `always` means full edit history is visible",
    "the organization-settings UI exposes the policy as an input (select) with DOM id `#id_realm_message_edit_history_visibility_policy`, following the existing `#id_realm_<setting_name>` convention, whose value is the policy code"
  ],
  "reason": "The test binds only to the new setting's name, the conventional settings_config `<setting>_values` export with enum keys always/never (codes dereferenced, never hard-coded), and the convention-derived DOM id for the new UI control \u2014 all public contract surface a ticket would legitimately dictate. Assertions themselves check behavior (discard restores prior value; edit-history modal gated on policy) through pre-existing test interfaces, with no binding to private helpers, internal call signatures, or log wording."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product goal, option set, default, and UI location; the expected-behavior evidence pins down the exact setting name, the settings_config enum object shape, the DOM id, the save/discard behavior of the dropdown, and the 'never' semantics (suppressed edit-history UI and no client-side edit_history bookkeeping). Together these are concrete enough that two engineers would independently produce compatible implementations."
}
