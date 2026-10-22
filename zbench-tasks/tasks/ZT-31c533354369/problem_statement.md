# Sentry webhook integration: support `error` webhook payloads

## Background

Zulip ships a Sentry webhook integration (`zerver/webhooks/sentry/`) that receives POSTs from Sentry at `/api/v1/external/sentry` and turns them into Zulip messages. Sentry's webhook payloads wrap the interesting object inside a `data` dictionary; the integration currently recognizes payloads where `data` contains an `"event"` key (raw event/exception data) or an `"issue"` key (issue lifecycle actions).

Sentry — notably self-hosted Sentry installs (e.g. version 23.1.0) sending alerts through an internal integration — also sends payloads where the `data` dictionary's key is `"error"` instead of `"event"`. The Zulip integration does not recognize this shape, so these notifications are dropped and the server logs:

```
ERR  [zulip.zerver.webhooks.unsupported] The '['error']' event isn't currently supported by the Sentry webhook
user: sentry-bot@zulip.**** ()
client: ZulipSentryWebhook
url: /api/v1/external/sentry
content_type: application/json
```

The result is that some Sentry alerts arrive in Zulip while others (the `error`-shaped ones) silently fail with the above server-side error.

## Required behavior

The Sentry webhook must accept payloads whose `data` dictionary contains an `"error"` key and render them exactly the way it renders the equivalent `"event"` payloads. The object under `data["error"]` carries the same fields the integration already consumes for events — `title`, `level`, `platform`, `timestamp`/`datetime`, `web_url`, `exception.values[*]` (with `stacktrace.frames`, each frame having `filename`, `context_line`, `pre_context`, `post_context`), `metadata`, `contexts`, etc. — plus a few extra fields such as `issue_url` and `issue_id` that don't change the rendering.

Concretely, for an `error` payload representing an unhandled JavaScript exception with:

- `data.error.title` = `"ReferenceError: blooopy is not defined"`
- `data.error.level` = `"error"`
- `data.error.platform` = `"javascript"`
- `data.error.datetime` = `"2019-08-19T20:58:37.391000Z"`
- `data.error.web_url` = `"https://sentry.io/organizations/test-org/issues/1170820242/events/bb78c1407cea4519aa397afc059c793d/"`
- one exception value whose stacktrace has a single frame with `filename` = `"/runner"`, `context_line` = `"<meta charset=utf-8>"`, `pre_context` = `["<!doctype html>", "<html>"]`, and `post_context` = `["<title>JS Bin Runner</title>", "", "<style type=\"text/css\">", "  body {", "    margin: 0;"]`

the integration must post a message under the topic `ReferenceError: blooopy is not defined` with exactly this content:

````
:orange_circle: **New exception:** [ReferenceError: blooopy is not defined](https://sentry.io/organizations/test-org/issues/1170820242/events/bb78c1407cea4519aa397afc059c793d/)
```quote
**level:** error
**timestamp:** <time:2019-08-19T20:58:37+00:00>
**filename:** /runner
```

Traceback:
```javascript
     <!doctype html>
     <html>
---> <meta charset=utf-8>
     <title>JS Bin Runner</title>

     <style type="text/css">
       body {
         margin: 0;
```
````

This is the same format the integration already produces for exception events delivered under `data["event"]`: the circle emoji is chosen from the event's `level`, the title links to `web_url`, the quote block shows level, the timestamp (truncated to whole seconds, rendered as a `<time:...>` element in UTC), and the offending frame's filename, and the traceback code block is syntax-highlighted according to the event's `platform` (`javascript` here), showing the frame's pre-context, context line (marked with `--->`), and post-context, with non-marked lines indented to align.

No new formatting logic should be invented for `error` payloads — the requirement is that an `error`-shaped payload produces byte-identical output to what the same object would produce if it had been delivered under the `event` key. All existing behaviors (message events, issue actions, deprecated-exception handling, and rejection of genuinely unsupported payload shapes) must be preserved.

## Notes

- Only the payload envelope differs (`data.error` vs. `data.event`); handle the dispatch so both keys route to the same event-rendering path.
- The integration's fixture directory (`zerver/webhooks/sentry/fixtures/`) contains examples of the currently supported payload shapes; an `error`-shaped payload is identical in spirit to `event_for_exception_js.json`-style payloads but nested under `data["error"]` and carrying extra fields like `issue_url`/`issue_id`.
