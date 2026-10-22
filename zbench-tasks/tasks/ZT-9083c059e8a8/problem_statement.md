# Show the channel type icon in channel/topic links inside rendered messages

## Background

In the Zulip web app, the left sidebar's channel list already distinguishes channel types visually: a hash icon for public channels, a lock icon for private (invite-only) channels, a globe icon for web-public channels, and an archived indicator for archived channels. There is an existing shared Handlebars template, `web/templates/decorated_channel_name.hbs`, that renders a channel name together with the appropriate privacy/archived icon; it takes the channel's sub object under a `stream` parameter.

However, when a message body contains a channel link (a `#channel` mention) or a channel-topic link, the rendered message content always displays the channel name prefixed with a plain `#` character, regardless of the channel's type. A private channel mentioned in a message looks identical to a public one.

The post-processing of rendered message content happens on the client in `web/src/rendered_markdown.ts` (`update_elements`), which locates `a.stream` and `a.stream-topic` / `a.message-link` anchors inside message content and rewrites their display text/HTML. Topic links are currently rendered via the `web/templates/topic_link.hbs` template.

## Required behavior

1. **Channel links** (`a.stream` anchors in rendered message content, identified by their `data-stream-id` attribute): instead of setting the text to `#<channel name>`, the client must render the link's contents using the shared `decorated_channel_name.hbs` template, so the channel name appears with the icon matching its type (public, private/invite-only, web-public, or archived).
2. **Channel-topic links** (`a.stream-topic` / message links rendered through `topic_link.hbs`): the template must now be able to render the decorated channel name (via the `decorated_channel_name` partial) instead of a plain `#`-prefixed name, so topic links also show the correct channel type icon.
3. The decoration must be correct for every channel type. For a channel whose sub object has `invite_only: true`, the lock treatment must result; for `is_web_public: true`, the globe treatment; for `is_archived: true`, the archived treatment. This works by passing the channel's real sub object through to the template — the template already knows how to pick the icon from those flags.
4. Behavior for channels the client does not know about (no sub object available for the given stream id) should remain as it is today; the new decoration path applies when the sub can be looked up.
5. No other observable behavior of message rendering (hrefs, topic display names, empty-topic handling, highlight preservation, etc.) may change.

## Interface requirements

- Stream links (`a.stream` elements) in rendered message content must be re-rendered by calling the pre-existing shared template `web/templates/decorated_channel_name.hbs` (which renders the channel name with its privacy/archived icon), passing the channel's sub object (from sub_store) under the template's existing `stream` parameter; the sub carries the existing fields `stream_id`, `name`, `invite_only`, `is_web_public`, `is_archived`.
- The `topic_link.hbs` template context gains a new field `stream`: the full sub object for the linked channel (so the template can render the decorated channel name via the `decorated_channel_name` partial). The existing context fields (`channel_id`, `channel_name`, `topic_display_name`, `is_empty_string_topic`, `href`) are unchanged and no other new fields are added.
- Stream/topic links whose channel is private (`invite_only`), web-public, or archived must still go through the same `decorated_channel_name` render path with the corresponding sub flags intact (the decoration reflects the channel's privacy/archived state).

## Notes for implementation

- The lookup of the sub object should be keyed off the anchor's `data-stream-id` (for channel links) or the channel id parsed from the topic link's href (for topic links), consistent with how these elements are already processed in `rendered_markdown.ts`.
- Take care to preserve existing behavior around search-highlight spans inside these anchors, which the current code already handles when rewriting link contents.
