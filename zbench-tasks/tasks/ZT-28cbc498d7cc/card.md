# ZT-28cbc498d7cc -- combined-feed-ui: Add placeholder text to empty combined feed.

- lang: web   issue: #31602   tier: B
- fix: https://github.com/zulip/zulip/commit/28cbc498d7cc1692d7f68635c6bec4fc125773b6
- f2p: web/tests/message_view.test.cjs
- p2p: web/tests/message_list.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature (UI behavior change)",
  "reason": "Real, plausibly-assigned feature: empty combined feed previously showed no banner; the change makes it show a specific placeholder with a link to public channels. The hidden test grades observable outcome deterministically \u2014 it sets up an in:home filter, triggers show_empty_narrow_message(), and asserts the banner's title and link content. Asserting the specific short message/link is the behavior itself (matching the file's established pattern for every other narrow case), not an incidental long-string or whole-snapshot pin. Test fails before (old code returned the default banner / skipped banner for combined feed) and passes after."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When the user is in the combined feed view (narrow filter `in: home`) and it contains no messages, an empty-feed banner must be shown (previously the combined feed suppressed this banner) with the title \"There are no messages in your combined feed.\"",
    "For non-spectator users, the banner body must be the HTML sentence \"Would you like to <a href=\\\"#narrow/channels/public\\\">view messages in all public channels</a>?\" \u2014 i.e. the phrase \"view messages in all public channels\" is a link to the hash URL #narrow/channels/public; both title and body go through the standard translation machinery."
  ],
  "reason": "The test asserts through the pre-existing banner interface (narrow_banner.show_empty_narrow_message rendering into the existing .empty_feed_notice_main container via the existing empty_narrow_html template). The only new surface it pins is the banner's user-visible title text, body copy, and link destination for the empty combined feed \u2014 user-facing strings and a URL that a ticket/design spec would legitimately dictate. No private helpers, internal fields, or implementation-specific mock targets are referenced, so with the copy specified in the brief the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the desired placeholder text and styling, and the expected-behavior evidence pins down the exact strings, the link target (#narrow/channels/public, which supersedes the older /#narrow/streams/public wording in the issue), the triggering filter (in: home), and that translation machinery is used \u2014 enough for two engineers to build compatible implementations."
}
