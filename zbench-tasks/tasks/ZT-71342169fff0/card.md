# ZT-71342169fff0 -- stream_settings: Update organization default dropdown labels.

- lang: web   issue: #35212   tier: B
- fix: https://github.com/zulip/zulip/commit/71342169fff0c85cbd9f66c055a1f9a28eae4d3f
- f2p: web/tests/compose.test.cjs, web/tests/compose_ui.test.cjs, web/tests/compose_validate.test.cjs
- p2p: web/tests/settings_config.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "ui-behavior-improvement",
  "reason": "This is a real behavior change, not string churn: the 'Organization default' dropdown label now dynamically embeds the realm's current topics-policy value (realm_topics_policy_values[realm.realm_topics_policy].description), so the rendered option text varies with org state. That is deterministically observable in node unit tests via get_stream_topics_policy_values() output \u2014 a short, stable string assertion, not a long snapshot pin. The visible test-diff changes (adding realm_topics_policy to test realm fixtures) are consistent with grading this outcome: old code ignores the field while new code requires it, and a hidden assertion on the inherit-option description fails before and passes after. Nothing here pins exact long output, HTML snapshots, versions, or time-gated behavior."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test changes only populate the pre-existing realm API field `realm_topics_policy` (with its pre-existing enum value `allow_empty_topic`) in test fixture realm state so existing tests continue to run once the fix reads that field. `realm_topics_policy` and `realm_topics_policy_values` (including `allow_empty_topic`) already exist at the base commit, as evidenced by the code diff spreading `realm_topics_policy_values` and indexing it without defining it. No new function names, fields, DOM ids, or messages are bound by the test; it exercises behavior purely through pre-existing interfaces."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the exact label pattern and names the two dropdowns (message retention period and the topics-policy / 'general chat topic' dropdown) in channel creation and channel management. The evidence shows that code exercised by compose paths now depends on the realm-level realm_topics_policy value being defined, which pins down that the organization default must be resolved from realm_topics_policy in shared logic. Together these give a determinate, checkable outcome: label format, affected dropdowns, data source for the parenthetical value, and the constraint that compose-path resolution of topics policy reads realm_topics_policy."
}
