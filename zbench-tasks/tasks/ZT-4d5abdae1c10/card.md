# ZT-4d5abdae1c10 -- info_overlay: Add printing support for informational overlays.

- lang: web   issue: #10214   tier: B
- fix: https://github.com/zulip/zulip/commit/4d5abdae1c103598e35e37fa7531290a87c28026
- f2p: web/tests/hotkey.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, plausibly-assigned feature (issue asks to make the keyboard-shortcut overlay printable) implemented via a new Ctrl/Cmd+P hotkey. The hidden test grades observable behavior deterministically: keydown mappings resolve to the 'print' action (including non-Latin layouts and platform-specific Cmd vs Ctrl), Ctrl+Shift+P is not intercepted, and process_keydown dispatches to info_overlay.print_current_pane only when an info overlay is open, returning false otherwise. No snapshot pinning, exact-string output, or incidental-format assertions \u2014 the mocked-call and mapping assertions fail before the change and pass after it."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "Ctrl+P (Cmd+P on macOS) becomes a global Zulip hotkey whose action name in the keydown mapping table is `print`; it is available everywhere, not only in message views (message_view_only: false).",
    "Platform handling follows the standard Ctrl/Cmd convention: on macOS only Cmd+P triggers the `print` action and bare Ctrl+P is not mapped; on other platforms Ctrl+P triggers it and the Cmd modifier does not.",
    "Ctrl+Shift+P (and Alt+P, which remains the compose-preview toggle) must NOT be intercepted, because Ctrl+Shift+P opens a private-browsing window in Firefox; the shifted combination must fall through to the browser.",
    "The `web/src/info_overlay` module gains an exported public function `print_current_pane()` that prints the currently displayed pane of the informational overlay; the hotkey handler must delegate the `print` action to this function.",
    "Behavioral gating: when an informational overlay is open (as reported by the existing `overlays.info_overlay_open()`), the print hotkey invokes `info_overlay.print_current_pane()` exactly once and the keydown event is consumed (handler returns true / preventDefault); when no informational overlay is open, the keydown is NOT consumed, so the browser's native print of the current page proceeds."
  ],
  "reason": "The test binds only to new contract surface a ticket would naturally pin: the hotkey action name `print` (the pre-existing mappings test enumerates every hotkey by its action name, so any new binding must declare one), the Ctrl/Cmd/platform semantics, the deliberate non-interception of Ctrl+Shift+P (a user-facing browser-compat requirement), and a single public entry point `info_overlay.print_current_pane()` on the module that owns the feature. The gating check uses the pre-existing `overlays.info_overlay_open()` interface, and the dispatch-to-module assertion follows the codebase's uniform convention that hotkey.ts delegates each action to one exported function of the owning module \u2014 a brief stating these requirements lets the test grade correctness rather than name-guessing. Nothing in the test touches internal implementation choices such as the template name, DOM ids of the printed container, the afterprint cleanup, or blueslip warnings."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives the user-facing goal (print the full contents of the overlay pane), and the evidence plus interface requirements pin down the exact mechanism: a globally-mapped `print` action on Ctrl/Cmd+P, non-Latin layout support, Ctrl+Shift+P fall-through, an exported info_overlay.print_current_pane(), and consume-vs-passthrough gating on overlays.info_overlay_open(). Two engineers following this brief would produce compatible implementations."
}
