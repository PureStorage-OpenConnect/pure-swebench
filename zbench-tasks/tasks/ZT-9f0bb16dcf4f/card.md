# ZT-9f0bb16dcf4f -- buddy list: Show status-text in tooltips only if not already visible.

- lang: web   issue: #35238   tier: B
- fix: https://github.com/zulip/zulip/commit/9f0bb16dcf4fcf114538a5efa2128b6a7ca7b378
- f2p: web/tests/buddy_data.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix / UX behavior change",
  "reason": "Real, plausibly-assigned frontend fix with observable behavior: get_title_data gains a should_show_status parameter that suppresses the status text second_line when it's already visible in the buddy list. The hidden test deterministically asserts the new behavior (should_show_status=false yields empty second_line, true yields the status text) via small structured deepEqual checks on TitleData objects \u2014 it fails before (old 2-arg signature/behavior) and passes after, and grades outcome rather than pinning long strings or snapshots."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The exported function `buddy_data.get_title_data(user_ids_string, is_group)` gains a third required boolean parameter `should_show_status`, so its signature becomes `get_title_data(user_ids_string: string, is_group: boolean, should_show_status: boolean)`.",
    "When `should_show_status` is false and the user has a status text set, the returned `TitleData.second_line` must be the empty string (the status text is suppressed); all other fields (`first_line`, `third_line`, `show_you`, `is_deactivated`) are unaffected.",
    "When `should_show_status` is true, `get_title_data` behaves exactly as before: an individual user's status text appears in `second_line`, and group/bot/deactivated-user results are unchanged."
  ],
  "reason": "The test's only new binding is the third boolean parameter added to `buddy_data.get_title_data`. That function already exists at the base commit and is the module's exported, cross-module interface (consumed by click_handlers), so a ticket could legitimately dictate extending it with a `should_show_status` flag and its suppression semantics \u2014 this is contract surface, not a private helper or mock target. Everything else the test touches is pre-existing: the `TitleData` shape (`first_line`/`second_line`/`third_line`/`show_you`/`is_deactivated`) is asserted unchanged in existing cases, and `settings_config.user_list_style_values` / `user_settings.user_list_style` are pre-existing settings used only to set up state. Given the three contract items above in a brief, the test grades behavioral correctness (status text suppressed iff the flag is false) rather than name-guessing. It is not 'clean' because the new positional parameter and its exact semantics (empty string, not omitted field) would otherwise have to be guessed, and not 'coupled' because the binding is to a legitimately specifiable public-surface extension, not internal implementation choices \u2014 notably, the test does not constrain how `click_handlers` computes the flag (compact mode / truncation logic stays untested)."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product rule precisely (show status in tooltip only in Compact style or when the inline status is truncated), and the interface requirements pin down the exact API change to get_title_data and its semantics, so two engineers would independently produce compatible implementations."
}
