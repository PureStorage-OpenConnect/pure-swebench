# ZT-a8aefd843424 -- keyboard: Add shortcut to narrow to mentions.

- lang: web   issue: #11098   tier: B
- fix: https://github.com/zulip/zulip/commit/a8aefd8434246aa1ce4750dd12cb6e198900d443
- f2p: web/tests/hotkey.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Adds a Ctrl/Cmd+@ keyboard shortcut to narrow to mentions \u2014 a realistic, well-scoped feature task. The hidden test grades observable behavior deterministically: it asserts that specific keydown events (including modifier and non-latin-keyboard variants) map to the open_mentions_view action, which fails before the change and passes after. No snapshot pinning, exact-string brittleness, or format-over-behavior assertions; template/tooltip additions are untested incidentals."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "A new keyboard shortcut Ctrl+@ (Cmd+@ on macOS) navigates the user to the mentions view (the `#narrow/is/mentioned` location).",
    "The shortcut's action is registered in the hotkey system under the action identifier `open_mentions_view` (following the existing convention of identifiers like `open_starred_message_view`), so keydown resolution of Ctrl+@/Cmd+@ yields a hotkey named `open_mentions_view`.",
    "The shortcut is message-view-only: it must be active only when a message view/feed is the current context, and must not fire (resolve to no hotkey) outside the message view.",
    "The shortcut must work independently of keyboard layout: on non-Latin layouts, pressing Ctrl plus the physical key that produces '@' (e.g. Digit2) triggers the same `open_mentions_view` action, subject to the same message-view-only restriction."
  ],
  "reason": "The test exercises the pre-existing keydown-mapping interface (the same map_down/name-assertion pattern used for every existing hotkey in this suite), but binds to new surface: the Ctrl+@/Cmd+@ key combination, the action identifier string `open_mentions_view`, and its message_view_only gating. The key combination and view-only behavior are plainly product requirements. The action name is a new string, but hotkey action identifiers in this codebase form a de facto public registry with a strict naming convention (open_starred_message_view, open_combined_feed), and a ticket could legitimately pin it; handed these four requirements, a solver would be graded on correctness rather than name-guessing. Nothing in the test reaches into private helpers, stubs internals, or depends on the fix's module layout (the browser_history.go_to_location call and template changes are untested implementation detail)."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user-facing goal (a keyboard shortcut to narrow to @-mentions), the behavior evidence pins down the exact key (Ctrl/Cmd+@, layout-independent via the physical Digit2 key), the action name (open_mentions_view), and the message-view-only scoping, and the interface requirements confirm the target narrow (#narrow/is/mentioned). Together these define a determinate, independently checkable outcome."
}
