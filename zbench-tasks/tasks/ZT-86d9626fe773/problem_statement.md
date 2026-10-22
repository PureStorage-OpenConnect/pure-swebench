# Add a keyboard shortcut to open the "Set a status" modal

## Background

Zulip lets users set a status (an emoji plus a short status message) via a modal dialog, normally reached through the personal menu in the UI. The web client already exposes a public function that opens this dialog: `open_user_status_modal()` in `web/src/user_status_ui`. There is currently no keyboard shortcut to open it, which hurts the usability of the status feature for keyboard-driven users.

## Current behavior

- Pressing `Shift`+`Y` in the web app does nothing: the keypress is unmapped and falls through the hotkey system.
- The only way to open the "Set a status" modal is with the mouse via the personal/avatar menu.

## Required behavior

Add a global keyboard shortcut `Shift`+`Y` that opens the "Set a status" modal.

1. **Key binding.** Register `Shift`+`Y` in the web client's hotkey system (`web/src/hotkey.ts`). Pressing it must open the status modal by calling the existing `user_status_ui.open_user_status_modal()` function — do not reimplement the modal-opening logic.
2. **Availability.** The shortcut must be available in all views of the app (like other global shortcuts such as `g` for the gear menu), not restricted to views where a message list is active. It must be suppressed while the user is editing text (compose box, message edit, search input, other text fields, etc.), consistent with how other letter-key shortcuts behave.
3. **Non-Latin keyboard layouts.** The shortcut must follow the existing hotkey framework's layout handling so it works on non-Latin layouts: it should match by physical key position (browser key code `KeyY`) with Shift held, so e.g. a Russian-layout user pressing Shift on the key that produces `Н` still triggers it.
4. **Consumed keypress.** Once mapped, `Shift`+`Y` must be consumed by the hotkey system (triggering the status modal) rather than being treated as an unmapped key.
5. **Documentation.** Document the new shortcut wherever keyboard shortcuts are listed:
   - In the in-app keyboard shortcuts reference (the `?` menu / keyboard shortcuts modal), add it to "The Basics" section directly below the "Search messages" shortcut, labeled "Set status".
   - In the corresponding help-center documentation of keyboard shortcuts, and on the help page describing how to set a status, mention `Shift`+`Y` as a way to open the dialog.

## Interface requirements

- A new keyboard shortcut `Shift`+`Y` opens the "set status" modal; it is available in all views (not only when a message view is active) and only fires when the user is not editing text.
- The hotkey action registered for `Shift`+`Y` carries the action identifier `set_status` in the hotkey mapping system.
- Pressing `Shift`+`Y` opens the status modal by invoking the pre-existing public function `user_status_ui.open_user_status_modal()` from `web/src/user_status_ui`.
- The shortcut works on non-Latin keyboard layouts: it is matched by physical key position (code `KeyY`) with Shift held, consistent with the existing hotkey framework's layout handling.
- `Shift`+`Y` ceases to be an unmapped key; it is consumed by the hotkey system rather than falling through.
