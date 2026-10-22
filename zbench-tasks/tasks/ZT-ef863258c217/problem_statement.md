# Strip heading/title formatting from pasted single-element selections more robustly

## Context

Zulip's compose box intercepts rich-text paste events and converts the clipboard HTML to Zulip-flavored Markdown (`web/src/compose_paste.ts`, entry point `paste_handler_converter(paste_html: string): string`).

One deliberate behavior: when the entire copied selection lies within a single HTML element (e.g. the user selected text inside one `<h1>`, `<b>`, or `<del>`), we treat the element's styling as incidental and strip it, rather than converting it to Markdown syntax. The exceptions are elements needed to convey structure (`PRE`, `UL`, `OL`, `A`, `CODE`), which are retained. The current implementation checks whether the parsed clipboard body has a single element child and, if so, unwraps it by taking its `innerHTML` before Markdown conversion.

## The bug

When a user triple-clicks a page title/heading on many real websites (NY Times, Wikipedia, arXiv, ScienceDirect, etc., notably in Chrome on macOS) and pastes it into the compose box, the heading formatting is NOT stripped: the pasted text comes out as `# James Madison` instead of `James Madison`.

The cause is that real clipboard payloads for such selections are not a lone heading element. Browsers wrap the fragment with extra nodes, for example:

- HTML comment nodes such as `<!--StartFragment-->` and `<!--EndFragment-->`;
- a trailing `<br class="Apple-interchange-newline">`;
- empty or effectively-empty sibling elements (e.g. a `<div>` whose only content is such a `<br>`, or an empty `<div>` used for page layout);
- whitespace-only text nodes.

Because of these extra siblings, the "selection is within a single element" detection fails, the heading element is kept, and the Markdown converter emits a `#` prefix.

A related variant: the meaningful heading may itself be wrapped, e.g. an `<h1>` nested inside a styled `<div>` wrapper, or an `<h1>` whose visible text is inside a child `<span>`.

## Required behavior

Rework the single-element detection/unwrapping so that nodes carrying no real content do not defeat it. Concretely, when deciding whether the copied content is a single element (and when locating that element), the logic must ignore:

- comment nodes;
- whitespace-only text nodes;
- `<br>` elements (in particular Apple/Chrome interchange newlines);
- elements that contain no visible content (e.g. a `<div>` containing only a `<br>`, or an empty `<div>`).

After ignoring such nodes, if exactly one content-bearing element remains and it is not one of the structural elements to retain (`PRE`, `UL`, `OL`, `A`, `CODE`), its formatting must be stripped so the paste yields plain text. This must hold recursively enough to handle a heading wrapped in a single container div.

### Concrete expected outcomes

Each of these clipboard HTML payloads, passed to `paste_handler_converter`, must produce exactly the plain title text shown — no `#` prefix, no surrounding whitespace or trailing newline artifacts:

1. `<html><body><!--StartFragment--><h1 class="title" style="...">Enriched categories as a free cocompletion</h1><br class="Apple-interchange-newline"><!--EndFragment--></body></html>` → `Enriched categories as a free cocompletion`
2. An `<h2 ...>Abstract</h2>` followed by a `<div>` whose only content is `<br class="Apple-interchange-newline">` (with StartFragment/EndFragment comments) → `Abstract`
3. `<h1 ...><span class="mw-page-title-main">James Madison</span></h1>` followed by an empty layout `<div>` → `James Madison` (note the visible text lives in a child span; the heading styling must still be stripped)
4. A `<div>` wrapper containing only an `<h1>From Words to Vectors: Understanding the Magic of Text Embedding</h1>` (plus whitespace) → `From Words to Vectors: Understanding the Magic of Text Embedding`

### No double conversion

The unwrapping/stripping path must convert the content to Markdown exactly once. When the single element's contents are taken and then converted, the text must not be run through HTML-to-Markdown processing twice (which can manifest as spurious escaping of Markdown special characters or otherwise mangled output). For example:

- `<del>turtles are cool</del>` → `turtles are cool` (styling stripped since the selection is within one element, and the inner text emerges verbatim).

### Behavior to preserve

All existing paste conversions must keep working unchanged, including: stripping bold/italic when copied from within a single styled element; retaining structure for `PRE`/`UL`/`OL`/`A`/`CODE` outer elements (code blocks keep fenced formatting with language annotation, lists keep bullets/nesting, links keep their targets); and normal multi-element rich-text pastes still converting to Markdown (bold → `**`, etc.).

Note: the conversion runs in the web client; the implementation should use standard DOM APIs (`document`, `Node`, `HTMLElement`, etc.) available in a browser environment.
