# Add a keyboard shortcut to open the mentions view

## Background

Zulip's web app lets users jump to most common views from the keyboard: there are hotkeys for the combined feed, recent conversations, starred messages (e.g. an action registered as `open_starred_message_view`), and so on. However, there is currently no keyboard shortcut to narrow to the messages that @-mention you (the mentions view, reachable in the UI at the `#narrow/is/mentioned` location). Users who triage their mentions frequently must reach for the mouse or the left sidebar to get there.

## Required behavior

Add a keyboard shortcut, **Ctrl+@** (**Cmd+@** on macOS), that navigates the user to the mentions view — i.e., it takes the user to the `#narrow/is/mentioned` narrow, exactly as if they had clicked "Mentions" in the left sidebar.

Details:

1. **Registration and naming.** The shortcut must be wired into the web app's hotkey system as a new action with the identifier `open_mentions_view`, following the existing naming convention of view-opening actions such as `open_starred_message_view`. When a keydown for Ctrl+@ (Cmd+@ on macOS) is resolved by the hotkey system, it must resolve to a hotkey whose name is `open_mentions_view`, and dispatching that action must navigate to the mentions view.

2. **Platform modifier.** On macOS the shortcut uses the Cmd key; on all other platforms it uses the Ctrl key. Follow the app's existing convention for Cmd/Ctrl-equivalent shortcuts (the same mechanism used by shortcuts like Ctrl+K / Cmd+K for search).

3. **Message-view-only scope.** The shortcut must be active only when a message view/feed is the current context. When the user is not in a message view (for example, in a non-message-feed view or another context where message-view-only shortcuts are suppressed), pressing Ctrl+@ / Cmd+@ must resolve to no hotkey at all — the keypress should not trigger the action and should fall through as if no shortcut were registered. This mirrors how other message-view-only shortcuts (such as `s` for star message) are scoped.

4. **Keyboard-layout independence.** The shortcut must work regardless of the user's keyboard layout. On non-Latin layouts (e.g. Russian), where the character produced by a key differs from the Latin layout, pressing Ctrl plus the physical key that produces `@` on a standard layout (the physical `Digit2` key, since `@` is Shift+2) must trigger the same `open_mentions_view` action. Use the app's existing mechanism for layout-independent shortcut matching (matching on the physical key code where character-based matching fails). The message-view-only restriction from point 3 applies identically on non-Latin layouts.

5. **Discoverability.** Add the new shortcut to the in-app keyboard shortcuts help (the popup opened with `?`) and any user-facing keyboard-shortcuts documentation, listed alongside the other navigation shortcuts, so users can discover it.

## Interface requirements

- A new keyboard shortcut Ctrl+@ (Cmd+@ on macOS) navigates the user to the mentions view (the `#narrow/is/mentioned` location).
- The shortcut's action is registered in the hotkey system under the action identifier `open_mentions_view` (following the existing convention of identifiers like `open_starred_message_view`), so keydown resolution of Ctrl+@/Cmd+@ yields a hotkey named `open_mentions_view`.
- The shortcut is message-view-only: it must be active only when a message view/feed is the current context, and must not fire (resolve to no hotkey) outside the message view.
- The shortcut must work independently of keyboard layout: on non-Latin layouts, pressing Ctrl plus the physical key that produces '@' (e.g. `Digit2`) triggers the same `open_mentions_view` action, subject to the same message-view-only restriction.

## Acceptance criteria

- In a message view, pressing Ctrl+@ (Cmd+@ on macOS) navigates to `#narrow/is/mentioned`.
- The hotkey system resolves that keypress to an action named `open_mentions_view`.
- Outside a message view, the same keypress resolves to no hotkey and does nothing.
- On a non-Latin keyboard layout, Ctrl (or Cmd on macOS) plus the physical `Digit2` key produces the same behavior, including the message-view-only restriction.
