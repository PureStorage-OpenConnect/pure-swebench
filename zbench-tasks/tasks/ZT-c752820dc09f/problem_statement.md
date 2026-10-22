## Markdown processor double-formats mentions that are wrapped in a markdown link

### Observed behavior

In Zulip's markdown processor, the mention syntax handling does not check whether a mention appears as the text of an explicit markdown link. As a result, when a message contains a mention wrapped in link syntax, e.g.:

```
[@**King Hamlet**](https://example.com/some/custom/url)
```

the content is processed by **both** the mention processor and the inline link processor. This double formatting causes two problems in the rendered output:

1. The custom URL supplied in the link is overwritten by the narrow/permalink URL that the mention processor generates for the mentioned user (or wildcard/group mention).
2. A useless extra `<a>` element (from the inline link processor) is left in the output wrapping the mention element.

A real-world consequence of this: messages that format a mention as a link with a specific destination (for example, a reminder for a channel message that links to a particular topic/message) end up pointing at the wrong place, because the intended link target is clobbered by the mention-generated link.

### Expected behavior

A mention that is formatted with an explicit markdown link should not be double-processed. The author's chosen link destination should be preserved rather than being replaced by the mention processor's generated narrow link, and the rendered HTML should not contain a redundant nested/extra `<a>` element.

### Where to look

The relevant logic is in the server-side markdown processor (the mention handling and inline link handling in `zerver/lib/markdown/`). The fix should make mention processing aware of link context so that mentions inside `[...](...)` link syntax are not converted into mention narrow links that override the explicit link.
