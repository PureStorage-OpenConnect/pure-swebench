# `e` keyboard shortcut should work for anonymous (spectator) users

## Context

Zulip's web app can be browsed by anonymous users ("spectators") without logging in. Spectators have read-only access: most interactive actions are gated, and attempting a gated action opens a login/signup modal (via `spectators.login_to_access()` in `web/src/spectators.ts`).

However, some actions are intentionally available to spectators. One of these is viewing a message's source/raw markdown: a spectator can open the message actions menu on any message and successfully use "View message source", which opens the message-source viewer (with the option to copy the raw content).

## Current (buggy) behavior

The `e` keyboard shortcut is the keyboard equivalent of this action. For a logged-in user, pressing `e` on the selected message opens message editing, or the read-only message source viewer when the message is not editable by them. For a spectator, pressing `e` does not open the message source viewer; instead it pops up the login/signup modal.

This is inconsistent: the exact same operation succeeds for a spectator through the mouse-driven message menu, but the keyboard route is blocked by the login gate.

The cause is in the keyboard shortcut dispatch in `web/src/hotkey.ts`: `e` is included in the set of shortcuts that are unconditionally blocked for spectators, so the handler calls `spectators.login_to_access()` before the shortcut's normal action can run.

## Required behavior

- When an anonymous/spectator user (i.e., `page_params.is_spectator` is true) presses `e` with a message selected, the login/signup modal must NOT be shown — `spectators.login_to_access()` must not be invoked for this keypress.
- Instead, the keypress must be handled like the normal `e` shortcut and reach the message edit/view-source flow, which for a spectator (who can never edit) resolves to opening the read-only message source viewer for the selected message — the same result as choosing "View message source" from the message actions menu.
- Behavior for logged-in users must be unchanged: `e` still opens the message editor when the message is editable and the source viewer otherwise.
- Other shortcuts that are legitimately login-gated for spectators must remain gated; only `e` should be removed from the spectator-blocked set.

## Notes for implementation

- The spectator gating for hotkeys lives in the keydown processing path of `web/src/hotkey.ts` (the code path exercised by `process_keydown`), where a list/switch of shortcut keys triggers `spectators.login_to_access()` when `page_params.is_spectator` is true. The `e` case should fall through to the standard handling that ends up in the message edit module, which already knows how to show the source viewer when editing is not permitted.
- No new user-facing strings or settings are needed; this is purely making the keyboard path match the existing menu behavior.
