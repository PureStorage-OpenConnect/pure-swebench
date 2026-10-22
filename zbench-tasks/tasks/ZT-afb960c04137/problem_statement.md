# Highlight alert words in channel/topic links and message links

## Background

In the Zulip web client, users can configure "alert words." When a message containing one of the user's alert words arrives, the server marks the message as alerted (`message.alerted === true`), and the client-side rendering pipeline highlights occurrences of those words in the message body by wrapping them in `<span class='alert-word'>…</span>` (see `web/src/alert_words.ts`, which provides this highlighting logic, and `web/src/rendered_markdown.ts`, which post-processes rendered message content via `update_elements`).

Rendered messages can contain links to channels/topics and to specific messages. During post-processing, `rendered_markdown.ts` rewrites anchors matching `a.stream-topic` and `a.message-link` into decorated links, rendering them through the Handlebars templates `web/templates/topic_link.hbs` (channel + topic links) and `web/templates/channel_message_link.hbs` (links to a specific message, i.e. links with a `/near/<id>` component). Both templates currently receive the topic's display name as a plain-text context value named `topic_display_name`, which the template escapes on output.

## Current (buggy) behavior

When an alert word appears inside the topic name portion of a channel/topic link or message link (e.g. a message containing `#**GSoC>GSoC 2024 project ideas@1761334**` for a user whose alert word appears in that topic name), the alert word is highlighted in the ordinary message text but **not** inside the rendered channel/topic or message links. The topic display name in those links renders as plain text with no `alert-word` highlighting, which is inconsistent with the rest of the message.

## Required behavior

1. When the containing message is marked as alerted (`message.alerted` is true), any of the user's alert words appearing in the **topic display name** of a decorated channel/topic link (`a.stream-topic`) or message link (`a.message-link`) must be highlighted the same way as in message bodies: each match wrapped in `<span class='alert-word'>…</span>`.
2. The topic display name must be **HTML-escaped first**, and highlighting applied to the escaped text. For example, a topic display name of `topic name > still the topic name` must be escaped to `topic name &gt; still the topic name` before any highlight markup is inserted. Alert-word spans added afterward must survive rendering as real markup (not be escaped away).
3. When the message is not alerted, or no alert words match, the link must render exactly as before from the user's perspective: the escaped topic display name, unchanged.
4. Empty-string topics must continue to work: they still render the translated "general chat"-style empty-topic display name and still set the `is_empty_string_topic` flag in the template context.
5. Both link kinds are covered: channel/topic links rendered via `topic_link.hbs` (context also includes `channel_id`, `stream`, `channel_name`, `is_empty_string_topic`, `href`) and message links rendered via `channel_message_link.hbs` (context also includes `channel_name`, `stream`, `is_empty_string_topic`, `href`). The channel-name portion of the link (rendered via `decorated_channel_name.hbs`) is unaffected.

### Example

For a message with `alerted: true`, the user's alert words set to `["alert"]`, and a link to topic `important alert topic`, the decorated link's topic portion must render as:

```html
important <span class='alert-word'>alert</span> topic
```

Similarly, a message link to topic `alert` must render its topic portion as `<span class='alert-word'>alert</span>`.

## Interface requirements

- The topic-link and channel-message-link templates (`topic_link.hbs`, `channel_message_link.hbs`) must receive the topic display name as **pre-escaped HTML** under the context key `topic_display_name_html`, replacing the previous plain-text `topic_display_name` key. The templates must render this value unescaped (triple-stache) so embedded highlight markup displays as real HTML.
- The topic display name passed to these templates must be HTML-escaped (e.g. `>` becomes `&gt;`) before any highlight markup is added.
- When the containing message is alerted (`message.alerted` is true), alert words in the topic display name of channel/topic links and message links must be highlighted using the existing alert-word highlighting mechanism (wrapping matches in `<span class='alert-word'>…</span>`), applied after escaping.
- When the message is not alerted or no alert words match, the templates receive the escaped topic display name unchanged, with empty-string topics still handled via the translated empty-topic display name and the `is_empty_string_topic` flag.

## Notes for implementation

- The relevant post-processing lives in `web/src/rendered_markdown.ts` (`update_elements`), which already has access to the message object (and therefore `message.alerted`) for the content being processed.
- Reuse the existing alert-word highlighting logic in `web/src/alert_words.ts` rather than reimplementing matching; matching semantics (word boundaries, case handling) must be identical to message-body highlighting.
- Be careful about escaping order: escape the raw topic display name once, then insert highlight spans. Do not double-escape, and do not allow raw topic text (which can contain `<`, `>`, `&`) to be injected unescaped into the DOM.
