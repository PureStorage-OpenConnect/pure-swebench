# Include cross-realm system bots in the compose-box mention typeahead

## Background

Zulip installations have a small set of "cross-realm" system bots (e.g. **Welcome Bot**, **Notification Bot**, **Email Gateway Bot**). These bots live in a special system realm rather than in the user's own realm, and the web client tracks them separately from the realm's regular (active) users. They are flagged with `is_system_bot: true` in the user objects the client receives, and they are among the first accounts a new user interacts with — the first private message most people receive comes from Welcome Bot, and users often try to test Zulip by replying to or mentioning it.

## Current behavior

Cross-realm bots never appear in the compose box's `@`-mention typeahead (nor the silent-mention `@_` variant). Because the typeahead builds its candidate list only from the realm's own user list, typing `@Welcome` or `@Notification` in the compose box produces no suggestion for these bots, so users cannot easily @-mention them.

## Required behavior

Cross-realm system bots must be offered as suggestions in the compose-box mention typeahead, in both the regular mention (`@`, `@**`) and silent mention (`@_`, `@_**`) forms:

1. **Candidate inclusion.** The set of people considered by the mention typeahead must include the cross-realm bots (drawn from wherever the client stores cross-realm users) in addition to the realm's active users. Cross-realm bot suggestions must be regular "user"-type suggestion items with the same shape and rendering as any other user suggestion (full name, user id, email, etc.).
2. **Query matching.** A cross-realm bot appears only when it matches the typed query, using exactly the same person-matching rules already applied to regular users (e.g. `@o` matches "Welcome Bot" and "Notification Bot" the same way it matches "Othello"). If no cross-realm bot matches (e.g. a query matching nothing in their names), none is shown; adding them must not cause suggestions to appear for queries that should yield an empty list.
3. **Ranking.** Matching cross-realm bots are ranked *below* every other kind of matching suggestion: after matching regular users, after wildcard/broadcast mentions (`all`, `everyone`, `topic`, ...), and after matching user groups. Among themselves, cross-realm bots are ordered alphabetically by full name (so "Notification Bot" precedes "Welcome Bot").
4. **Both mention forms.** The above applies identically whether the user is composing a regular mention or a silent mention; the silent variant continues to show user groups and users per existing rules, with matching cross-realm bots appended after those.
5. **No other regressions.** Existing typeahead behavior for regular users, deactivated users, broadcast mentions, user groups, slash commands, and stream/topic suggestions must be unchanged apart from the addition of the cross-realm bots.

For example, with cross-realm bots Welcome Bot and Notification Bot known to the client, typing `@o` mid-message should suggest the matching realm users first (e.g. Othello, Cordelia), then any matching wildcard mention, then Notification Bot and Welcome Bot last, in that order.

## Interface requirements

(none)
