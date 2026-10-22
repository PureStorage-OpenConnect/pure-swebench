# Show "general chat" in digest email conversation headers for empty-topic messages

## Background

Zulip supports messages sent with an empty topic name. Throughout the product, an empty topic is presented to users under a display name — "general chat" — rendered in italics rather than as a blank string. The helper `get_topic_display_name` already exists and returns the localized user-facing display name for a topic (including the "general chat" name for an empty topic, translated into a given language).

Digest emails summarize recent activity as a list of "hot conversations". Each hot conversation includes a header identifying the channel and topic of the conversation, produced in two variants: a plain-text version and an HTML version (used by the email templates).

## Current behavior

When a hot conversation in a digest email is for a channel message with an empty topic ("general chat"), the conversation header shows no topic at all: the topic portion of both the plain and HTML header variants is an empty string.

## Required behavior

When building digest email hot-conversation headers, an empty topic must be rendered using its user-facing display name "general chat" instead of an empty string, in both the plain and HTML header variants.

Concretely, for a conversation whose topic name is the empty string:

- **Plain header variant**: the topic portion must contain the display name "general chat" (obtained via the existing `get_topic_display_name` helper), so the header reads like `<channel name> > general chat` in plain text.
- **HTML header variant**: the topic portion must contain the display name wrapped in exactly this markup: `<span class='empty-topic-display'>general chat</span>` — the class name is `empty-topic-display` and the class attribute uses single quotes. This span exists so email CSS can italicize the pseudo-topic name. The email styling should render `.empty-topic-display` in italics, matching how the empty-topic display name appears elsewhere in the product.
- The display name must be localized: it should be produced in the digest recipient's language (i.e., resolve the translated string in the context of the user receiving the digest, not the server default).

Conversations with a non-empty topic must be unaffected: their topic continues to be rendered as the raw topic name with no wrapping span, exactly as before, in both variants.

The change must apply to the digest pipeline end to end: when digests are generated for users (the bulk digest-sending path that assembles the `hot_conversations` context for the digest email), the header data for each hot conversation (`first_few_messages` header, with its `plain` and `html` fields) must reflect the behavior above. The same rendering should apply anywhere digest content is produced from this code path (e.g., the in-browser digest preview uses the same context).

## Interface requirements

- In digest email hot-conversation headers, an empty topic must be rendered using its user-facing display name 'general chat' (from the existing `get_topic_display_name`, in the digest recipient's language) in both the plain and HTML header variants, instead of an empty string.
- In the HTML header, the empty-topic display name must be wrapped in exactly `<span class='empty-topic-display'>...</span>` — class name 'empty-topic-display', single-quoted class attribute — so email styling can italicize it; non-empty topics are rendered unwrapped as before.

## Notes

- Only the topic portion of the header changes; channel names and the rest of the header structure are unchanged.
- Take care that the HTML variant emits the span markup literally (not HTML-escaped), while non-empty topic names continue to receive whatever escaping they get today.
