# Render emoji in desktop notifications

## Background

Zulip's web client sends desktop (browser/OS) notifications when a user receives relevant messages. The notification text is derived from the message's rendered HTML content, which is converted to plain text for display in the notification.

In Zulip's rendered message HTML, emoji appear as inline elements rather than literal Unicode characters:

- **Standard Unicode emoji** are rendered as non-image elements (e.g. `<span>`) carrying class markup of the form `class="emoji emoji-<hex>[-<hex>...]"`, where the class name encodes the emoji's Unicode code point(s) as hyphen-separated hexadecimal values. For example, the octopus emoji is rendered with `class="emoji emoji-1f419"`, and multi-codepoint sequences (such as ZWJ sequences) include every code point, e.g. `class="emoji emoji-1f468-200d-1f373"` for the "man cook" emoji (👨 + ZERO WIDTH JOINER + 🍳).
- **Custom/realm emoji** (which have no Unicode equivalent) are rendered as `<img>` elements whose `alt` attribute contains the emoji's name (e.g. `:party_parrot:`).

## Current (broken) behavior

When a message containing emoji triggers a desktop notification, the emoji do not show up in the notification text. The plain-text conversion in the desktop notification rendering pipeline does not translate the rendered emoji elements into anything useful, so emoji are effectively dropped from the notification content.

## Required behavior

Emoji must appear in desktop notification text:

1. In the desktop notification rendering pipeline, each rendered emoji element in the message content must be replaced with a textual representation before the notification text is produced.
2. For a non-image emoji element with Zulip's rendered-emoji class markup (`class="emoji emoji-<hex>[-<hex>...]"`), the replacement must be the actual Unicode emoji character(s): parse each hyphen-separated hexadecimal code point from the class name and concatenate the corresponding Unicode characters into a single string. Examples:
   - An element with class `emoji emoji-1f419` becomes the string `"🐙"` (U+1F419).
   - An element with class `emoji emoji-1f468-200d-1f373` becomes the full ZWJ sequence `"👨‍🍳"` (U+1F468 U+200D U+1F373) — all code points must be included, in order.
3. For an `img` emoji element (custom/realm emoji with no Unicode equivalent), the replacement must be the element's `alt` text.

## Interface requirements

- The `web/src/ui_util` module must gain an exported function `convert_emoji_element_to_unicode(element)` that takes a (jQuery-wrapped) rendered-emoji DOM element and returns a string: the Unicode emoji character(s) that element represents.
- For a non-image emoji element carrying Zulip's rendered-emoji class markup (`class="emoji emoji-<hex>[-<hex>...]"`, hyphen-separated hexadecimal Unicode code points), `convert_emoji_element_to_unicode` must parse each hex code point and return them concatenated as a single string — e.g. an element classed `emoji emoji-1f419` yields `"🐙"`, and a multi-codepoint sequence like `emoji emoji-1f468-200d-1f373` yields `"👨‍🍳"`.
- For an `img` emoji element (custom/realm emoji with no Unicode equivalent), `convert_emoji_element_to_unicode` must return the element's `alt` text instead.
- The desktop notification rendering code must use this conversion so that emoji appear in notification text as described above.

## Notes for implementation

- The conversion function should work on an element regardless of surrounding document context (it operates on the element's class attribute / `alt` attribute alone), so it can be applied to each emoji element found in a message's rendered content during notification text generation.
- Multi-codepoint handling must be general: any number of hyphen-separated hex code points in the class name must be decoded and joined, not just the two-or-three-codepoint examples above.
