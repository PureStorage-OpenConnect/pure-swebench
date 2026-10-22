# Save the open compose draft when the browser window loses focus

## Background

Zulip's web client has a compose box where users write messages. To protect users from losing in-progress work, the client already saves the current compose content as a draft in several situations (e.g., periodically and when the compose box is closed). However, if the user has an open, in-progress message and the browser reloads the Zulip tab (or the tab is otherwise torn down) while the compose box is open, the in-progress content can be lost, because nothing saves the draft when the user switches away from the window.

## Current behavior

When the browser window loses focus (the user clicks into another application or another browser window/tab), the web client does nothing with the open compose draft. If the tab is subsequently reloaded or discarded, any compose content written since the last draft save is lost.

## Required behavior

When the `window` object receives a `blur` event, the client must save the user's in-progress compose draft (if there is one), using the same draft-saving logic used elsewhere in the compose system for preserving the currently open message. If there is no meaningful in-progress content, the existing draft-saving logic's normal handling of that case applies — this change only needs to trigger the save attempt on blur.

The result is that switching away from the Zulip window snapshots the open draft, so a later reload of the tab cannot lose more than what was typed since the window last lost focus.

## Interface requirements

- When the window loses focus, the user's in-progress compose draft must be saved so no work is lost — i.e., a `blur` handler on `window` saves the current draft.
- This blur handler must be registered as part of compose setup initialization: it must be attached inside the existing `compose_setup.initialize()` entry point (in `web/src/compose_setup.js`), which callers invoke once at startup.
- The handler must be attached through the codebase's standard jQuery event mechanism on the window object — `$(window).on("blur", ...)` — not via a raw `window.addEventListener` call.

## Notes for implementation

- The draft-saving behavior should reuse the existing compose-draft update/save machinery (see `web/src/drafts.ts`) rather than introducing a new persistence path, so that the draft saved on blur is identical in form to drafts saved by other triggers.
- The handler should be safe to run when the compose box is closed or empty (it should simply not create spurious drafts in that case, consistent with how the existing draft-update logic behaves).
