# Pasting an image copied from Chrome inserts the image URL instead of uploading the image data

## Context

Zulip's web client has a paste handler for the compose box (`web/src/compose_paste.ts`). When the user pastes, the clipboard often contains multiple representations of the same content (e.g. `image/png` data plus a `text/html` fragment). The handler inspects the HTML representation to decide how to treat the paste: if the HTML is essentially a single image, the handler should ignore the HTML and let the image *data* flow through the normal drag-and-drop/upload path, so the image is uploaded to the Zulip server and a link to the uploaded copy is inserted. Otherwise, the HTML is converted to Markdown and inserted as text.

The module already contains a classifier that answers the question "does this pasted HTML fragment consist of just one image?" (`is_single_image` in `web/src/compose_paste.ts`), and it already handles several real-world clipboard payloads (e.g. images copied from Zulip itself, LibreOffice content, macOS Terminal content).

## Current (buggy) behavior

When a user right-clicks an image in Chrome (observed on Windows 11), chooses **Copy Image**, and pastes into the Zulip compose box:

- The clipboard genuinely contains the raw image data.
- However, Chrome's accompanying `text/html` clipboard entry wraps the `<img>` tag in extra nodes — HTML comment markers and whitespace-only text nodes. A representative payload looks like:

  ```html
  <html>
  <body>
  <!--StartFragment--><img src="https://example.com/some/image.png"/><!--EndFragment-->
  </body>
  </html>
  ```

- The single-image classifier fails to recognize this payload as a single image, because of the comment nodes (`<!--StartFragment-->`, `<!--EndFragment-->`) and the newline/whitespace text nodes surrounding the `<img>` element.
- As a result, the paste is handled as HTML-to-Markdown conversion: the compose box ends up containing the source URL of the image (as image Markdown pointing at the remote URL) instead of an uploaded copy of the image.

This is broken in practice because the source URL is frequently not publicly accessible (e.g. images from Google Photos or other authenticated pages), so recipients see a broken image.

## Required behavior

When the pasted HTML fragment consists of a single `<img>` element accompanied only by "noise" nodes — HTML comment nodes and text nodes that are empty or contain only whitespace — the client must classify the paste as a single image. Concretely:

1. Given the Chrome-style payload above (an `<img>` inside `<body>`, surrounded by `<!--StartFragment-->`/`<!--EndFragment-->` comments and newline text nodes), the single-image classifier must return true.
2. Consequently, pasting a copied image from Chrome must result in the clipboard's image data being uploaded through the compose box's existing file-upload flow (the same path used when an image file is dropped onto the compose box), not in the remote URL being inserted as text.

## Constraints / non-regressions

- Only comment nodes and empty/whitespace-only text nodes may be ignored when deciding whether the fragment is a single image. HTML containing any other meaningful sibling content (visible text, tables, multiple images, other elements) must continue to be treated as rich HTML and converted to Markdown as today.
- Existing classification results must be preserved: payloads currently recognized as single images (e.g. a bare `<img>` copied from Zulip, LibreOffice single-image exports) must still be recognized, and payloads currently rejected (e.g. LibreOffice tables, macOS Terminal text, mixed image+text fragments) must still be rejected.

## Interface requirements

(none — implement within the existing paste-handling module; the single-image classification entry point already exists as `is_single_image` in `web/src/compose_paste.ts` and its name and call sites should remain unchanged)
