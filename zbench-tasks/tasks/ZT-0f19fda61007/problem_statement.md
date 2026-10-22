# Mark messages as read in `is:dm` and `-is:dm` views

## Background

In the Zulip web client, whether a message view automatically marks messages as read is governed by a design rule: a view should mark messages as read if and only if it never breaks up conversations — that is, for any conversation (a channel topic or a DM thread), the view shows either all of its messages or none of them. Views built purely from structural narrowing (e.g., a channel, a topic, a specific DM conversation) satisfy this; views that filter within conversations (e.g., a `search:` keyword, `is:starred`, `is:mentioned`) do not, and must not mark messages as read.

The narrow-filter logic that implements this lives in the web client's `Filter` class (`web/src/filter.ts`).

## Current behavior

A view narrowed to `is:dm` (all direct messages) or to `-is:dm` (everything except direct messages) does **not** mark messages as read, even though neither of these narrows splits any conversation: `is:dm` shows every DM conversation in full and no channel messages, and `-is:dm` shows every channel conversation in full and no DMs.

## Required behavior

1. A view whose narrow is exactly `is:dm` must automatically mark messages as read, the same way conversation views do.
2. A view whose narrow is exactly `-is:dm` (the negation of `is:dm`) must likewise automatically mark messages as read.
3. Consistent with the general design, combining `is:dm` or `-is:dm` with a term that filters *within* conversations — e.g., a `search:` keyword — must **not** mark messages as read.
4. Optionally (nice to have, only if it falls out simply from the implementation): redundant combinations such as `-is:dm` together with a channel and/or topic filter, or `is:dm` together with a specific DM-conversation filter, may also mark messages as read. Do not add significant complexity to support this.

## Behavioral details for the `-is:dm` narrow

The `-is:dm` narrow must be treated by the filter logic as a complete-conversations view with the following observable characteristics in the web client:

- It is recognized as containing no partial conversations, and therefore eligible for marking messages as read.
- It is **not** classified as a DM-only view (it is not "contains only private messages").
- It can be applied locally on the client (messages can be filtered client-side against this narrow without a server round-trip).
- It is **not** classified as a personal filter, a single-conversation view, or a channel view; it is a view that may contain multiple conversations.
- It does **not** enable the "next unread topic" or "next unread DM conversation" navigation buttons.
- It is not treated as having exactly channel+topic operators.

Note that `is:private` is a legacy alias for `is:dm` and must behave identically wherever it is still accepted (including its negated form).

## Scope

The change is expected to be confined to the web client's narrow/filter classification logic (primarily `web/src/filter.ts`), extending the set of narrows recognized as safe for mark-as-read to include `is:dm` and negated `is:dm`, while preserving current behavior for all other narrows (in particular, any narrow containing a `search:` term must remain ineligible for mark-as-read).
