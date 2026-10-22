# Rank bots below user groups (and fellow-tier humans) in composebox typeahead

## Background

Zulip's web client shows a typeahead when composing: typing `@` in the message body suggests people, wildcard mentions, user groups, and bots; the direct-message recipient box uses the same underlying recipient-sorting logic. That logic lives in the web frontend's typeahead-sorting module (`web/src/typeahead_helper.ts`, chiefly the recipient-sorting function used by the composebox typeahead in `web/src/composebox_typeahead.ts`). It ranks candidates through a series of relevance buckets (exact string match on name/email, subscription to the current stream, direct-message/mention history, name or email prefix match quality, etc.) and concatenates the buckets in priority order.

## Current behavior

Bot users are ranked too aggressively:

- In the `@`-mention typeahead, bots are suggested **before** user groups.
- Within the sorted recipient list, bots are interleaved with human users of the same relevance — a bot whose name matches the query can appear above equally-matching human users.

## Required behavior

Bots should be demoted, without otherwise disturbing the existing ranking:

1. **Bots after user groups.** In the `@`-mention typeahead, user groups must appear before bot users. Human users and wildcard/broadcast mentions keep their existing placement; only bots move from before the groups to after them.
2. **Humans before bots within each relevance bucket.** In the recipient-sorting logic, every existing relevance bucket that can contain both humans and bots must emit its human (non-bot) users first, then its bot users. Whether a user is a bot is determined by the `is_bot` flag on the user object. The relative order *among* humans and *among* bots within a bucket must be exactly what the current criteria already produce (PM counts, alphabetical fallback, etc.). This bucket-local demotion means a highly relevant bot (e.g. one matching the query) can still rank above humans from a strictly lower-relevance bucket — bots are not simply dumped at the very end of the whole list.
3. This applies both to stream-message composition (where subscriber status is part of the ranking) and to direct-message recipient suggestions.

### Illustrative example

Suppose the realm has human users with emails `a_user@zulip.org`, `b_user_1@zulip.net`, `b_user_2@zulip.net`, `b_user_3@zulip.net`, `zman@test.net` and bots `a_bot@zulip.com`, `b_bot@example.com`. For the query `b_user_1@zulip.net` (an exact email match, with no other candidate matching), the suggestions must be: the exact match `b_user_1@zulip.net` first, then the remaining human users in their existing fallback order (`a_user@zulip.org`, `b_user_2@zulip.net`, `b_user_3@zulip.net`, `zman@test.net`), then the bots (`a_bot@zulip.com`, `b_bot@example.com`). Previously, bots could appear ahead of some of those humans.

Similarly, for a name-prefix query such as `b` in a direct-message context where `b_user_1`–`b_user_3` and `b_bot` all match: all matching humans must precede the matching bots, whereas today `b_bot` can outrank a matching human with a lower PM count.

## Notes and constraints

- The change is purely about ordering; no candidates are added or removed from the suggestion list, and filtering/matching rules are unchanged.
- User objects flowing through the composebox typeahead should be treated as carrying `is_bot`; classification must be by that flag, not by name heuristics.
- All other typeahead orderings (streams, topics, emoji, slash commands, language, wildcard mentions relative to users) must be unaffected.
