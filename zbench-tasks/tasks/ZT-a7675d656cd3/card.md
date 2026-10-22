# ZT-a7675d656cd3 -- digest: Display italicized “general chat” when topic is empty.

- lang: py   issue: #36689   tier: B
- fix: https://github.com/zulip/zulip/commit/a7675d656cd3f7aaf49c7a6e200f7b327d5e7ded
- f2p: zerver.tests.test_digest.TestDigestEmailMessages.test_general_chat_in_digest
- p2p: zerver.tests.test_email_notifications

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned bug fix (digest emails show blank topic instead of 'general chat' for empty topics) with an observable outcome. The hidden test grades behavior deterministically: it constructs a digest with an empty-topic message and uses targeted assertIn checks on the header's HTML and plain-text content, not a full snapshot. Fails before the fix (no 'general chat' text) and passes after. The HTML assertion does pin the span/class markup, but that markup is the user-visible rendering the fix introduces (italicized display styling hook), a short substring rather than a whole rendered snapshot, and fully deterministic \u2014 well within acceptable brittleness."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "In digest email hot-conversation headers, an empty topic must be rendered using its user-facing display name 'general chat' (from the existing get_topic_display_name, in the digest recipient's language) in both the plain and HTML header variants, instead of an empty string.",
    "In the HTML header, the empty-topic display name must be wrapped in exactly <span class='empty-topic-display'>...</span> \u2014 class name 'empty-topic-display', single-quoted class attribute \u2014 so email styling can italicize it; non-empty topics are rendered unwrapped as before."
  ],
  "reason": "Nearly all assertions go through interfaces that already exist at base (digest context structure, mock targets, get_recent_topics cache, RealmAuditLog/AuditLogEventType, the 'general chat' display name). The one new binding is the exact user-visible HTML markup for empty topics (span + 'empty-topic-display' class with single-quoted attribute), which is public email-output surface a spec would dictate \u2014 comparable to a DOM id for a new UI element \u2014 not a private helper or internal layout. With that markup stated in the brief, the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the goal (show italic 'general chat' instead of no topic in digest emails), and the expected-behavior evidence pins down the observable contract: the hot-conversation header's html field must contain <span class='empty-topic-display'>general chat</span> and the plain field must contain 'general chat', for an empty-topic channel message flowing through the bulk digest path. Interface requirements specify the exact markup and the use of get_topic_display_name with recipient-language localization. This is determinate and checkable by two independent engineers."
}
