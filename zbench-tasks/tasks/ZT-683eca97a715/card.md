# ZT-683eca97a715 -- stream-settings: Replace "Not subscribed" tab with "Available".

- lang: web   issue: #35919   tier: B
- fix: https://github.com/zulip/zulip/commit/683eca97a715c25d6f302f5418abb6a7adfe3855
- f2p: web/tests/stream_settings_ui.test.cjs
- p2p: web/tests/hash_util.test.cjs, web/tests/stream_edit.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Not a pure rename: beyond relabeling the tab, triage_stream gains a real behavior change \u2014 the Available tab now also excludes unsubscribed streams the user lacks permission to subscribe to (can_toggle_subscription check). The hidden test grades observable, deterministic filtering outcomes (which stream objects survive filtering under given panel params and sort orders), not exact rendered strings or snapshots. This is a plausible assigned UI-behavior task in the Zulip web client, gradable fail-before/pass-after via the node-based stream_settings_ui tests."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The channel-settings left panel's \"Not subscribed\" tab is replaced by an \"Available\" tab, and the boolean flag in the left-panel filter parameters (the params object accepted by stream_settings_ui's exported redraw_left_panel / produced by get_left_panel_params) is renamed from `show_not_subscribed` to `show_available`; when true, the panel shows only channels the user is not subscribed to (subscribed channels are rejected)."
  ],
  "reason": "The test is a pure rename of an existing, already-tested surface: every assertion previously bound to the `show_not_subscribed` boolean in the left-panel params now binds to `show_available`, with identical behavioral expectations (filtering, search, sort orders). All behavior it checks existed at the base commit; the only new binding is the single field name `show_available`, which is a one-to-one consequence of the user-visible product rename ('Not subscribed' tab \u2192 'Available' tab) and would naturally be pinned in a ticket describing the rename. It is not an internal choice the author invented independently of the spec \u2014 the field name mirrors the tab key ('available'), URL hash ('#channels/available'), and label ('Available') that a design spec would dictate. Notably, the test does NOT bind to the genuinely new internal behavior in the fix (rejecting unsubscribed channels the user lacks permission to join via stream_data.can_toggle_subscription), nor to renamed internal helpers like is_available_stream_tab_active, so no deeper implementation coupling exists. Handed the one contract item above, a solver would be graded on correctness, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product goal (rename tab, new /available URL, show joinable channels, docs update), and the expected-behavior evidence pins down the exact frontend contract: the filter param rename from show_not_subscribed to show_available with unchanged reject-subscribed semantics, plus preserved search and sort behavior. Together these give a determinate, checkable outcome."
}
