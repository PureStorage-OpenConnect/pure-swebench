# Make the informational overlay (keyboard shortcuts / message formatting / search operators) printable via Ctrl+P

## Background

Zulip's web app has an informational overlay, opened from the gear menu (e.g., "Keyboard shortcuts"), implemented in `web/src/info_overlay`. It has three tabbed panes: "Keyboard shortcuts", "Message formatting", and "Search operators". Each pane's content would be useful as a printed reference card.

## Current behavior

With the overlay open, pressing Ctrl+P invokes the browser's native page print. The printout shows exactly what the browser tab currently renders: the grayed-out main Zulip page behind the modal, plus only the visible portion of the scrollable overlay pane. Content scrolled off-screen is cut off, so there is no reliable way to print a pane's full contents.

## Required behavior

When the informational overlay is open and the user presses the print shortcut (Ctrl+P; Cmd+P on macOS), Zulip must intercept the keystroke and print the **entire contents of the currently displayed pane** of the overlay — including content currently scrolled out of view — instead of letting the browser print the underlying page. Using the browser's default print formatting for that content is acceptable; a nicer ref-card style is a bonus, not a requirement.

When no informational overlay is open, the keystroke must not be intercepted anywhere in the app: the browser's normal print of the current page must proceed untouched.

## Interface requirements

- Ctrl+P (Cmd+P on macOS) becomes a global Zulip hotkey whose action name in the keydown mapping table is `print`; it must be registered as available everywhere, not only in message views (i.e., `message_view_only: false`).
- Platform handling follows the app's standard Ctrl/Cmd convention: on macOS only Cmd+P maps to the `print` action and bare Ctrl+P is not mapped; on all other platforms Ctrl+P maps to it and the Cmd modifier does not.
- Ctrl+Shift+P must NOT be intercepted, because in Firefox it opens a private-browsing window; the shifted combination must fall through to the browser. Alt+P likewise remains the existing compose-preview toggle and is unaffected.
- The `web/src/info_overlay` module must export a public function `print_current_pane()` that prints the currently displayed pane of the informational overlay; the hotkey handler must delegate the `print` action to this function.
- Behavioral gating: when an informational overlay is open (as reported by the existing `overlays.info_overlay_open()`), the print hotkey must invoke `info_overlay.print_current_pane()` exactly once and consume the keydown event (the handler returns true / calls preventDefault). When no informational overlay is open, the keydown must not be consumed, so the browser's native print dialog for the current page appears as usual.
- The mapping must work on non-Latin keyboard layouts via the physical key: e.g., on a Cyrillic layout, Ctrl plus the physical `KeyP` key (producing the character `з`) must trigger the `print` action, following the same physical-key resolution the app already uses for other Ctrl-modified shortcuts.

## Notes

- The mapping-table entry and the overlay-open gating are separate layers: `print` is a globally registered Ctrl-key action, and the decision to consume the event versus let the browser handle it happens at dispatch time based on whether the informational overlay is open.
- Update user-facing documentation of keyboard shortcuts if the codebase's conventions call for documenting new hotkeys.
