# Restore image pasting for content copied from Microsoft Excel

## Background

When a user copies a range of cells in Microsoft Excel, the OS clipboard contains multiple representations of the selection: plain text, an HTML rendering of the cells, and a rendered image of the cell range.

In older versions of Zulip, pasting an Excel selection into the compose box inserted the rendered **image** of the cell range, which users found very convenient. In current versions, a plain paste (Ctrl+V) instead consumes the HTML/text representation, so the user only gets a text conversion of the cells — the image option is effectively gone.

## How the paste pipeline works today

The web client's paste handling lives in the `copy_and_paste` module (`web/src/copy_and_paste.ts`, unit-tested against its public exports). On a plain paste (Ctrl+V), the handler inspects the clipboard's `text/html` payload:

- If the HTML is essentially a single `<img>` element, the handler treats the paste as an **image paste**: it does not convert the HTML to Markdown, and instead lets the clipboard's image data go through the normal image/file paste path.
- Otherwise, the HTML is run through `paste_handler_converter`, which converts it to Zulip-flavored Markdown text.

On paste-without-formatting (Ctrl+Shift+V), content is always pasted as text.

Because Excel's clipboard HTML is a `<table>`, not a lone `<img>`, the single-image check returns false, the HTML/text branch wins, and the image representation on the clipboard is never used.

## Required behavior

1. **Plain paste (Ctrl+V) of an Excel selection must be treated as an image paste.** The "is this an image paste?" check must recognize clipboard HTML that originates from Microsoft Excel / Office and answer yes, so that the rendered image of the cell range from the clipboard is inserted instead of a text conversion.

   Excel/Office clipboard HTML is identifiable by markers such as: `<meta name=ProgId content=Excel.Sheet>` and `<meta name=Generator content="Microsoft Excel 15">` metadata; Office/Excel XML namespaces on the `<html>` element (`urn:schemas-microsoft-com:office:office`, `urn:schemas-microsoft-com:office:excel`, the `vml` namespace); `xl`-prefixed CSS classes on cells (e.g. `class=xl65`); and `<!--StartFragment-->`/`<!--EndFragment-->` comment markers. Detection should be robust for a real Excel clipboard export exhibiting these traits (full document with `<head>`, `<style>` block of `mso-*` rules, and a `<table>` body).

2. **Paste-without-formatting (Ctrl+Shift+V) of an Excel selection must still paste text.** The Excel HTML must continue to route through the existing `paste_handler_converter`, producing the cells' text content. For a one-column Excel table whose two cells render as `$ 20.00` and `$ 30.00`-style currency values, the conversion should yield each cell's text as its own paragraph (blank-line separated), preserving the cell text content — e.g. a two-cell column containing "$ 20.00" and "$ 7.00" converts to text where `$ 20.00` and `$ 7.00` appear as separate blank-line-separated blocks. So both options remain available to the user: plain paste gives the image, paste-without-formatting gives the text.

3. **Non-Excel behavior is unchanged.** Ordinary HTML (Google Sheets spans, formatted rich text, links, etc.) must keep converting to Markdown text on plain paste exactly as before; only genuinely single-image HTML and Excel/Office clipboard HTML take the image path.

## Interface requirements

- The `copy_and_paste` module must export a public function `is_single_image(paste_html: string): boolean` that reports whether pasted clipboard HTML should be treated as an image paste. (This decision was previously an internal check for a lone `<img>` element; it must now be a public export, and callers use it on plain Ctrl+V to decide between the image-paste path and the formatted-text-paste path.)
- `is_single_image` must return `true` for clipboard HTML originating from Microsoft Excel (Office/Excel clipboard export: Excel ProgId/Generator metadata, Office namespaces, `xl`-prefixed cell classes, StartFragment markers), so that a plain paste of Excel cells is inserted as an image rather than converted text.
- Pasting Excel clipboard HTML with paste-as-plain-formatting (Ctrl+Shift+V) must continue to route through the existing `paste_handler_converter`, yielding the cell text content as formatted text.
