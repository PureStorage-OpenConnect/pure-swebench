# Pasting syntax-highlighted text from VS Code into the compose box doubles every newline

## Context

Zulip's web app intercepts paste events in the compose box and converts pasted HTML clipboard content into Zulip-flavored Markdown (see `paste_handler_converter` in `web/src/compose_paste.ts`, which drives an HTML-to-Markdown conversion). This works well for many sources (Google Docs, Google Sheets, Etherpad, web pages), but pasting from VS Code with syntax highlighting enabled produces mangled output.

## Steps to reproduce

1. In VS Code, open a new tab and type several lines, e.g.:

   ```
   a
   b
   c
   ```

2. Set the tab's language mode to Markdown (or any mode other than plain text, so VS Code puts syntax-highlighted HTML on the clipboard).
3. Select all and copy.
4. Paste into a Zulip compose box in the web app.

## Current (buggy) behavior

Every newline is doubled — a blank line is inserted between each original line:

```
a

b

c
```

The problem does not occur when the VS Code language mode is "Plain Text", nor when using the browser's "Paste as plain text", which shows the bug is in how the HTML clipboard flavor is converted. Pasting the same clipboard content into other applications (e.g. a GitHub comment box) does not double the newlines. Reproduced on Windows 11 with Chrome 142.

## Why this happens (clipboard shape)

When syntax highlighting is active, VS Code places HTML on the clipboard where the whole selection is wrapped in an outer `<div>` styled with `white-space: pre` (plus color/font styles), and **each line is wrapped in its own child `<div>`**, with the line text inside `<span>` elements. A representative clipboard payload looks like:

```html
<html>
<body>
<!--StartFragment--><div style="color: #cccccc;background-color: #1f1f1f;font-family: 'Fira Code Retina', Consolas, 'Courier New', monospace;font-weight: 350;font-size: 12.852px;line-height: 17px;white-space: pre;"><div><span style="color: #cccccc;">authentication-methods</span></div><div><span style="color: #cccccc;">export-and-import</span></div><div><span style="color: #cccccc;">postgresql</span></div><div><span style="color: #cccccc;">upload-backends</span></div><div><span style="color: #cccccc;">ssl-certificates</span></div><div><span style="color: #cccccc;">email</span></div></div><!--EndFragment-->
</body>
</html>
```

Zulip's current conversion emits two newlines between consecutive line-`<div>`s for this input (one blank line between every pair of lines), instead of one.

## Required behavior

Converting HTML of the shape above must produce exactly one newline between consecutive line-wrapping `<div>`s, with no leading or trailing blank lines. For the example payload above, the compose box content after paste must be exactly:

```
authentication-methods
export-and-import
postgresql
upload-backends
ssl-certificates
email
```

More generally: when each visual line of the pasted content is wrapped in its own `<div>` (as VS Code does for syntax-highlighted copies, inside a `white-space: pre` container), the resulting Markdown must preserve the original line structure verbatim — N source lines yield N output lines separated by single `\n` characters.

## Constraints

- The fix must not regress the existing paste conversions the handler already supports, in particular:
  - Etherpad-style content where each line is a `<div class="ace-line ...">` (including bulleted-list lines), which must continue to convert to single-newline-separated Markdown (e.g. `Test list:\n* Item 1\n* Item 2`).
  - Google Sheets / Google Docs paste handling (e.g. stripping `<style>` blocks, table conversion).
  - Intentional paragraph breaks from sources that genuinely represent blank lines (e.g. `<p>` paragraphs or explicit empty lines) must still come through as blank lines.
- The change belongs in the web client's paste-to-Markdown conversion path (`web/src/compose_paste.ts`); no server-side changes are expected.
