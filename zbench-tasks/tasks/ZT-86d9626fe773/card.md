# ZT-86d9626fe773 -- keyboard: Add shortcut to open set status modal.

- lang: web   issue: #16356   tier: B
- fix: https://github.com/zulip/zulip/commit/86d9626fe773bfd83f04e57fae08af99ba743546
- f2p: web/tests/hotkey.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Adds a Shift+Y keyboard shortcut that opens the set-status modal \u2014 a real, plausibly-assigned feature task with observable behavior. The hidden test grades outcome deterministically: it asserts the key maps to the set_status action (Latin and non-Latin layouts) and that pressing it calls user_status_ui.open_user_status_modal, all of which fail before the change and pass after. No snapshot pinning, exact-string brittleness, or version/time gating; the unmapped-keys string tweak is a direct consequence of Y becoming mapped, not incidental formatting."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "A new keyboard shortcut Shift+Y is added that opens the 'set status' modal; it is available in all views, not only when a message view is active, and only fires when the user is not editing text.",
    "The hotkey action registered for Shift+Y carries the action identifier `set_status` in the hotkey mapping system.",
    "Pressing Shift+Y must open the status modal by invoking the pre-existing public function `user_status_ui.open_user_status_modal()` from `web/src/user_status_ui`.",
    "The shortcut must work on non-Latin keyboard layouts, i.e. it is matched by the physical key position (code `KeyY`) with Shift held, consistent with the existing hotkey framework's layout handling.",
    "Shift+Y ceases to be an unmapped key (it must be consumed by the hotkey system rather than falling through)."
  ],
  "reason": "The test binds to three new/changed surfaces: the Shift+Y binding itself, the hotkey action name `set_status`, and the call to `user_status_ui.open_user_status_modal`. The keybinding and its all-views/not-editing-text semantics are user-visible product behavior a ticket would state. The mock/assert target `user_status_ui.open_user_status_modal` is a module and function that already exist at the base commit (the same modal opened from the personal menu), so requiring the shortcut to route through that existing public entry point is a legitimate spec item, not a guess at an invented internal. The only invented name is the action identifier `set_status`, a single registry key that a brief can dictate verbatim (comparable to specifying a DOM id); with these items in the brief, the test grades correct behavior rather than name-guessing. Note the test does not exercise the spectator guard in the fix, so that need not be in the contract."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue specifies the shortcut key (Shift+Y), its target (the set-status modal), and where to document it; the evidence pins down the exact action identifier (set_status), the invoked function (user_status_ui.open_user_status_modal), global availability with Shift, suppression while editing text, and physical-key (KeyY) matching for non-Latin layouts. Together these define a determinate, checkable outcome."
}
