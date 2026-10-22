# Rich clipboard payloads for "Copy link" on channel and topic links

## Background

Zulip's web app offers "Copy link" actions that put the URL of a channel (stream) or topic narrow onto the clipboard. Today, only a plain URL string is copied. When a user pastes into an HTML-capable destination (GitHub comments, Google Docs, email clients, etc.), they get a bare URL instead of a nicely formatted link like `#feedback > some topic`. When pasting into a browser address bar, the plain URL is exactly what's wanted.

The async Clipboard API cannot write arbitrary custom MIME types, so a browser clipboard can only carry multiple payload flavors when written via the synchronous copy mechanism.

## Required behavior

Copying a Zulip internal narrow link must place **multiple flavors** of the link on the clipboard simultaneously, so each paste target picks the flavor it supports:

1. **`text/plain`** — always set, and always exactly the original URL string, byte-for-byte unmodified. (This is what a URL bar or plain-text editor receives.)
2. **`text/html`** — set only when the link is a channel narrow URL (the standard `#narrow/channel/<id>-<name>...` hash format). Its value is an anchor of the exact form `<a href="LINK">LABEL</a>`, where `LINK` is the original URL.
3. **`text/x-gfm`** (GitHub-flavored markdown) — set under the same condition as `text/html`, with the exact form `[LABEL](LINK)`.

### Label construction

The human-readable `LABEL` is derived by decoding the narrow URL:

- Channel-only link (e.g. `.../#narrow/channel/1-Stream/`): label is `#<channel name>`, e.g. `#Stream`.
- Channel + topic link (e.g. `.../#narrow/channel/1-Stream/topic/normal.20topic`): label is `#<channel name> > <topic name>`, e.g. `#Stream > normal topic`. Note the topic name is the decoded, human-readable topic (URL-encoding such as `.20` for a space is decoded).
- Channel + topic + message link (contains a `/near/<message id>` component, e.g. `.../topic/normal.20topic/near/1`): label is the channel+topic label with the suffix ` @ 💬` appended — space, at-sign, space, then U+1F4AC (speech balloon emoji). Example: `#Stream > normal topic @ 💬`.

The channel name in the label comes from the channel referenced by the URL (resolved from the client's channel data), prefixed with `#`.

### Links that are not channel narrows

For any link that does not decode as a channel narrow — for example a direct-message narrow URL like `.../#narrow/dm/15-dm/near/43` — only the `text/plain` payload is written. No `text/html` or `text/x-gfm` data may be set for such links.

### Example payloads

For `http://zulip.zulipdev.com/#narrow/channel/1-Stream/topic/normal.20topic` (channel id 1, name "Stream"):

- `text/plain`: `http://zulip.zulipdev.com/#narrow/channel/1-Stream/topic/normal.20topic`
- `text/html`: `<a href="http://zulip.zulipdev.com/#narrow/channel/1-Stream/topic/normal.20topic">#Stream > normal topic</a>`
- `text/x-gfm`: `[#Stream > normal topic](http://zulip.zulipdev.com/#narrow/channel/1-Stream/topic/normal.20topic)`

For `http://zulip.zulipdev.com/#narrow/channel/1-Stream/`:

- `text/plain`: the URL itself
- `text/html`: `<a href="http://zulip.zulipdev.com/#narrow/channel/1-Stream/">#Stream</a>`
- `text/x-gfm`: `[#Stream](http://zulip.zulipdev.com/#narrow/channel/1-Stream/)`

## Interface requirements

- Add a new web module named `clipboard_handler` (importable as `"clipboard_handler"`) that exposes the public API for copying Zulip narrow links with rich formatting.
- The module exports an async function `copy_link_to_clipboard(link: string): Promise<void>` that copies the given Zulip internal link to the clipboard and resolves once the clipboard data has been written.
- Because the async Clipboard API cannot write custom MIME types, the copy must use the standard synchronous mechanism: register a `"copy"` event listener via `document.addEventListener`, trigger the copy with `document.execCommand("copy")`, and write all payloads via `setData` on the event's `clipboardData` object.
- All the payload rules above (`text/plain` always the exact original URL; `text/html` and `text/x-gfm` only for channel narrow links, with the label rules described) are part of this function's contract.

## Integration

Wire the existing "Copy link" user-facing actions for channel and topic links in the web app to this new module, so that a user-initiated copy produces the multi-flavor clipboard content described above.
