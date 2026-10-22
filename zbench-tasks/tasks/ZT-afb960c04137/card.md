# ZT-afb960c04137 -- alert_words: Highlight alert words in channel/topic links.

- lang: web   issue: #37830   tier: B
- fix: https://github.com/zulip/zulip/commit/afb960c04137fb518629356202c9456b4c48d402
- f2p: web/tests/rendered_markdown.test.cjs
- p2p: web/tests/markdown.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned bug fix: alert words were not highlighted inside channel/topic link text. The hidden test grades observable behavior deterministically \u2014 it asserts the template context receives the escaped/highlighted topic string (e.g. topic_display_name_html containing the alert-word span) via mocked templates, which fails before the fix and passes after. The asserted strings are short, behavior-defining outputs (escaping and highlight markup), not whole rendered-HTML snapshots or incidental formatting, so it is not brittle under the stated criteria."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The topic-link and channel-message-link templates (topic_link.hbs, channel_message_link.hbs) receive the topic display name as pre-escaped HTML under the context key `topic_display_name_html` (replacing the previous plain-text `topic_display_name` key), and render it unescaped so embedded markup displays",
    "The topic display name passed to these link templates must be HTML-escaped (e.g. '>' becomes '&gt;') before any markup is added",
    "When the containing message is marked as alerted (message.alerted is true), alert words appearing in the topic display name of channel/topic links and message links must be highlighted using the existing alert-word highlighting (which wraps matches in <span class='alert-word'>\u2026</span>), applied after escaping",
    "When the containing message is not alerted or no alert words match, the link renders the escaped topic display name unchanged, with empty-string topics still handled via the translated empty-topic display name and the is_empty_string_topic flag"
  ],
  "reason": "The test asserts behavior through pre-existing interfaces (update_elements, alert_words.set_words, template-context assertions already used at base, and the output format of the pre-existing highlight_alert_words helper). The only new name it binds to is the template context key `topic_display_name_html`, a rename that Zulip's enforced _html/triple-stache convention dictates once the requirement 'pass pre-escaped HTML with alert-word highlighting' is stated in a brief. No private helpers, internal signatures, or fix-invented internals are pinned, so a spec listing these contract items makes the test grade correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue plus the observable-behavior evidence and interface requirements pin down a determinate outcome: which links are affected, the exact context key rename (topic_display_name \u2192 topic_display_name_html), escaping-before-highlighting order, the alert-word span markup, the alerted-message gating, and empty-topic handling. Two engineers following this brief would produce compatible implementations."
}
