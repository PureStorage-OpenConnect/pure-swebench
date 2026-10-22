# Pygments highlighting failures should not cause message rendering to fail

## Context

Zulip's Markdown processor supports fenced code blocks with syntax highlighting. When a message contains a fenced code block with a language tag (e.g. ```` ```python ````), the fenced-code extension in `zerver/lib/markdown/fenced_code.py` runs the code through Pygments via the `CodeHilite.hilite` mechanism to produce highlighted HTML.

## Current (buggy) behavior

If the Pygments library raises an exception while highlighting a code block (some inputs can crash certain Pygments lexers — for example, a ```` ```matlabsession ```` block containing `>> foo()` followed by lines like `bar`, `...`, `baz` has been observed to do this), the exception propagates up out of the Markdown pipeline. The result is that posting the message fails entirely, and the API returns a 400 error to the client:

```json
{"result":"error","msg":"Unable to render message","code":"BAD_REQUEST"}
```

A bug in a syntax highlighter should never make a message impossible to send.

## Required behavior

1. Fenced-code highlighting must still be attempted through the existing `CodeHilite.hilite` mechanism used by `zerver.lib.markdown.fenced_code` — do not bypass or replace it.
2. If that highlighting call raises **any** exception, message rendering must not fail. Instead, the code block must gracefully fall back to being rendered as plain, unhighlighted code: HTML-escaped code text wrapped in the standard `<pre>`/`<code>` markup, preserving the language class on the element and the original code text verbatim — i.e. exactly the same output the renderer produces when no usable highlighting language is available for the block.
3. The failure must be recorded: log at **ERROR** level, including the exception traceback, with a log message that contains the phrase `Failed to highlight fenced code block`.

Concretely: rendering a message such as ```` ```python\nprint('hello')\n``` ```` while Pygments is broken must still succeed, producing output that contains a `<pre>` block with the original `print('hello')` text, and an ERROR log entry containing `Failed to highlight fenced code block` must be emitted. The message post must return success, not a 400.

The fallback must engage only when the highlighting call raises; when Pygments works normally, highlighted output must be produced exactly as before.

## Interface requirements

- When Pygments raises an exception while highlighting a fenced code block, message rendering must not fail: the block must fall back to plain, HTML-escaped code wrapped in the standard `<pre>`/`<code>` markup (preserving the language class and the original code text), exactly as if no highlighting language were usable.
- The highlighting failure must be logged at ERROR level (with exception traceback) using a message containing the phrase `Failed to highlight fenced code block`.
- Fenced-code highlighting must still be attempted through the existing `CodeHilite.hilite` mechanism used by `zerver.lib.markdown.fenced_code`; the fallback engages only when that call raises.
