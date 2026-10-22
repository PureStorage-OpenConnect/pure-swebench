# Redesign the connection error banner as a popup banner

## Background / current behavior

When the web app's long-polling `get_events` loop fails repeatedly, the client shows a connection error indicator. Today this is a static alert bar rendered from a template roughly like:

```html
<div class="alert alert_sidebar alert-error home-error-bar" id="connection-error">
    <div class="exit"></div>
    <strong class="message">{{ _('Unable to connect to Zulip.') }}</strong>
    {{ _('Updates may be delayed.') }}
    {{ _('Retrying soon…') }}
    <a class="restart_get_events_button">{{ _('Try now.') }}</a>
</div>
```

The server-events polling code (`web/src/server_events.js`) shows this element via `ui_report.show_error` when polling keeps failing and hides it via `ui_report.hide_error` when a poll succeeds.

## Required behavior

Replace the old `#connection-error` alert bar with a redesigned popup banner:

- **Style**: a red (error-styled) popup banner, with **no icon** on the left.
- **Text**: "Unable to connect to Zulip. Retrying soon…" — plain text, no bold portion, and the old "Updates may be delayed." sentence is removed. Text must remain translatable.
- **Action button**: labeled "Try now" (no trailing period), styled at a medium attention/priority level. Clicking it immediately retries the connection (restarts the get-events polling), just as the old "Try now." link did.
- The banner must be dismissible by the user (close/X affordance), and it must be programmatically dismissed as soon as a get-events poll succeeds, so the user never sees a stale connection error after connectivity is restored.
- Showing the banner repeatedly while the connection stays down must not stack duplicate banners; the existing single banner should remain (or be refreshed) until connectivity returns or the user dismisses it.

It is acceptable to leave a broader redesign of button attention levels and of the zephyr-mirror alert banner for later, but any CSS that only served the old `#connection-error` bar should be cleaned up where straightforward.

## Interface requirements

- Create a new web frontend module `web/src/popup_banners` that owns the connection-error popup banner UI, replacing the old `#connection-error` element managed via `ui_report`.
- That module must export a function `close_connection_error_popup_banner()` that dismisses the connection-error popup banner. The server-events polling code in `web/src/server_events.js` must import the module and call this function to clear the error indication whenever a get-events poll succeeds.
- The server-events code must no longer route connection-error display through `ui_report.hide_error`/`ui_report.show_error` on `#connection-error`; the popup-banner module must be the sole interface for showing and clearing the connection error.

## Compatibility notes

- The retry cadence and error-threshold logic in `server_events.js` (when the banner appears after repeated failures) should be preserved; only the display/dismissal mechanism and visual design change.
- All user-facing strings must go through the standard translation mechanism.
