# ZT-c8983c0d3183 -- popovers: Add x-gfm content type for copied Zulip links.

- lang: web   issue: #31813   tier: B
- fix: https://github.com/zulip/zulip/commit/c8983c0d3183e18f724b1e9214824b9fedc6e521
- f2p: web/tests/clipboard_handler.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, plausibly-assigned frontend feature: copying a Zulip link should populate the clipboard with plain-text, text/html, and text/x-gfm representations. The hidden test grades the observable outcome deterministically \u2014 it simulates the copy event and asserts the clipboard payload for several link shapes (topic, topic+message, stream, DM). The asserted strings are short, exact clipboard contents that ARE the behavior being added (the HTML anchor and markdown link a paste would produce), not incidental long-output snapshots or rendered-HTML dumps, so this is outcome-grading rather than format-pinning. Fails before the change (no clipboard_handler module, only plain-text copy), passes after."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "New web module `clipboard_handler` (importable as \"clipboard_handler\") exposing the public API for copying Zulip narrow links with rich formatting.",
    "The module exports an async function `copy_link_to_clipboard(link: string): Promise<void>` that copies the given Zulip internal link to the clipboard and resolves once the clipboard data has been written.",
    "Because the async Clipboard API cannot write custom MIME types, copying must use the standard synchronous mechanism: register a \"copy\" event listener via `document.addEventListener` and trigger it with `document.execCommand(\"copy\")`, writing all payloads via `setData` on the event's `clipboardData`.",
    "For every link, the clipboard's `text/plain` payload must be exactly the original URL string, unmodified.",
    "When the link decodes as a channel/topic narrow URL (the pre-existing `#narrow/channel/<id>-<name>...` hash format), the copy must additionally set a `text/html` payload of the form `<a href=\"LINK\">LABEL</a>` and a `text/x-gfm` (GitHub-flavored-markdown) payload of the form `[LABEL](LINK)`.",
    "The human-readable LABEL is `#<channel name> > <topic name>` for a channel+topic link; when the link also contains a `/near/<message id>` component the label gains the suffix ` @ \ud83d\udcac` (space, at-sign, space, U+1F4AC speech-balloon emoji); for a channel-only link the label is just `#<channel name>`.",
    "For links that are not channel narrows (e.g. direct-message narrow URLs), only the `text/plain` payload is set; no `text/html` or `text/x-gfm` data is written."
  ],
  "reason": "The test binds only to a new module/function intended as the public clipboard API (`clipboard_handler.copy_link_to_clipboard`), user-visible clipboard payloads (MIME types and exact label/link formatting), and the browser-standard execCommand+copy-event mechanism. The stubbed targets are browser globals (`document.addEventListener`, `document.execCommand`), not internal helpers of the fix, and a ticket would legitimately dictate the execCommand approach since it is the only way to write the required custom `text/x-gfm` MIME type. The URL hash formats and stream/people setup use pre-existing Zulip interfaces. With the listed contract in the brief, the test grades behavior, not name-guessing; nothing binds to internal choices like `topic_link_util.get_topic_link_content` or `execute_copy`."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product goal (dual plain-URL + rich HTML paste), and the expected-behavior evidence pins down the exact payload formats, label rules (including the /near message suffix and the DM exclusion), MIME types, and the required module/function name and copy mechanism. Together these give a determinate, checkable outcome."
}
