# ZT-c752820dc09f -- markdown: Don't double-process mentions formatted with a link.

- lang: py   issue: #38703   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/c752820dc09f564cf51a4d177d39d52ecc5042ae
- f2p: zerver.tests.test_markdown.MarkdownLinkTest.test_mentions_formatted_with_link
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavioral bug fix",
  "reason": "Fixes an observable rendering bug: link-producing mentions (channel/topic links) inside markdown links were double-processed. The change alters markdown output behavior testable through the pre-existing rendering interface (message rendering), not a refactor, docs, or bookkeeping change. Small, well-specified diff with a linked issue describing concrete input/output behavior."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "The hidden test only uses pre-existing interfaces: render_message_markdown, Message, get_client, example_user, and the long-standing rendered HTML classes 'stream', 'stream-topic', and 'message-link' (which it first sanity-checks against the base rendering behavior). It never imports or references the new symbol the fix introduces (BEFORE_LINK_PRODUCING_MENTION_ALLOWED_REGEX) nor any other new function, module, or invented string. Its assertion is a user-visible behavioral outcome \u2014 a mention wrapped in a markdown link renders as a plain <a> with escaped text instead of being double-processed \u2014 which any correct fix (e.g., a different regex name or an entirely different mechanism) would satisfy."
}
