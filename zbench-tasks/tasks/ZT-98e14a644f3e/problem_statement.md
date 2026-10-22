# Auto-linkification fails for URLs with a query string but no path

## Context

Zulip's message-rendering pipeline (`zerver/lib/markdown/`) automatically converts raw URLs typed into messages into clickable links (`<a>` tags). This works for most URLs, but there is a class of valid, common URLs that the auto-linkifier fails to recognize.

## Current (broken) behavior

A URL whose query string begins immediately after the host — i.e. the `?` follows the domain directly, with no path component in between — is not detected as a URL at all. It renders as plain text and is not clickable.

Example: sending the message

```
Check this: https://podcasts.google.com?feed=abc
```

renders the URL as plain text instead of a link. (Google Podcasts share links have exactly this shape, which is how users hit the bug.) The same URL *with* a path, e.g. `https://podcasts.google.com/?feed=abc`, links fine — the failure is specific to `?` appearing directly after the hostname.

## Required behavior

Rendering a message containing `scheme://host?query` must produce a working link whose href and link text include the full query string. Concretely, for each input message below, the rendered HTML must contain the indicated anchor:

1. Input: `Check this: https://podcasts.google.com?feed=abc`
   Rendered paragraph: `<p>Check this: <a href="https://podcasts.google.com?feed=abc">https://podcasts.google.com?feed=abc</a></p>`
   — the query string is part of the link; nothing before or after the URL is swallowed into it.

2. Input: `Is this https://google.com?`
   Rendered paragraph: `<p>Is this <a href="https://google.com">https://google.com</a>?</p>`
   — a bare `?` at the end of the URL with no query text after it is sentence punctuation, not part of the link. It must stay outside the anchor as literal text.

3. Input: `New logic inside parens: (see https://podcasts.google.com?feed=abc)`
   Rendered paragraph: `<p>New logic inside parens: (see <a href="https://podcasts.google.com?feed=abc">https://podcasts.google.com?feed=abc</a>)</p>`
   — when the URL sits inside parentheses and contains no unmatched `(` of its own, the closing `)` is not part of the link.

4. Input: `New logic with trailing dot: Go to https://podcasts.google.com?feed=abc.`
   Rendered paragraph: `<p>New logic with trailing dot: Go to <a href="https://podcasts.google.com?feed=abc">https://podcasts.google.com?feed=abc</a>.</p>`
   — a trailing period after the query string is sentence punctuation and stays outside the anchor.

In all cases the link text must equal the href exactly (standard Zulip behavior for auto-linkified raw URLs).

## Constraints / non-regression

- Existing linkification behavior must be preserved. In particular, complex URLs that already work must keep working unchanged, e.g. URLs with a path plus a long query string containing percent-encoding, parentheses inside query values, and many `&`-separated parameters (such as Graphite/render-style URLs like `http://host/render?width=700&from=-4hours&...&target=alias(foo.bar%2C%22label%22)&...`) must still be linkified in full.
- Trailing-punctuation trimming rules that apply to path-bearing URLs (dropping a final `.`, `?`, or unmatched `)`) must apply equally to these path-less query-string URLs, as shown in the examples above.
- The change belongs in the shared backend markdown processor so that all rendered messages (any sender, any recipient type — self-DM, DM, stream/channel message) get the behavior; it is not a frontend-only tweak.
