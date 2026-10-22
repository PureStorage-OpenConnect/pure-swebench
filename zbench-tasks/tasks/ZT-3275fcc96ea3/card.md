# ZT-3275fcc96ea3 -- popup_banners: Redesign connection banner to use new banner component.

- lang: web   issue: #31282   tier: B
- fix: https://github.com/zulip/zulip/commit/3275fcc96ea39f24fd67be8b76c9db2fd491274c
- f2p: web/tests/server_events.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "refactor/feature (UI component redesign with behavior changes)",
  "reason": "This is a real engineering task \u2014 migrating the connection-error UI from the legacy #connection-error/ui_report mechanism to the new banner component, with genuine behavior changes (a retry button with callback, fade-out close handling, and get-events vs. message-fetch error interplay). The hidden test is a deterministic Node test (server_events.test.cjs) exercising the event-loop error/success paths; the visible diff only swaps the mocked module from ui_report to popup_banners. It does not pin exact output strings, HTML/JSON snapshots, or any non-deterministic formatting, so it grades control-flow behavior rather than format. The coupling to the new module path/export names is a naming/spec-gap concern for later stages, not a verifiability failure, and this is not CSS-only polish \u2014 the graded logic lives in JS."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "A new web frontend module `web/src/popup_banners` owns the connection-error popup banner UI, replacing the old `#connection-error` element managed via `ui_report`.",
    "The module exports a function `close_connection_error_popup_banner()` that dismisses the connection-error popup banner; the server-events polling code (`web/src/server_events.js`) must call it (and therefore import the module) to clear the error indication when a get-events poll succeeds.",
    "The server-events code must no longer route connection-error display through `ui_report.hide_error`/`show_error` on `#connection-error`; the popup-banner module is the sole interface for showing/clearing the connection error."
  ],
  "reason": "The test's only new bindings are the module path `../src/popup_banners` and the exported function name `close_connection_error_popup_banner`, which it mocks in place of the old `ui_report` mock. Because Zulip's test harness fails on unused mocks, the test effectively requires that server_events imports this module and calls this export on the success path. That is a designed cross-module API boundary (shared by message_fetch and server_events), not a private helper or internal data structure \u2014 exactly the kind of module/function name a ticket or design brief would legitimately dictate ('add a popup_banners module exporting open/close functions for the connection error banner'). Given those names in the brief, the test grades behavior (error indicator cleared on successful poll) rather than name-guessing. It does not bind to the banner's internal structure, CSS classes, fade-out timing, or the `open_...` call signature, so nothing here is uncurable coupling."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives the concrete visual/text/interaction requirements (red banner, exact copy, 'Try now' button, no icon), and the interface requirements pin down the module name, exported function, caller, and the removal of the ui_report pathway \u2014 enough for two engineers to independently produce compatible implementations."
}
