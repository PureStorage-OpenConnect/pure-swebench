# Left sidebar filters: use word-prefix matching (like the right sidebar user search)

## Background

Zulip's left sidebar has three text filters: the topic filter (shown when a channel is zoomed in), the direct-message (DM) filter, and the channel-name filter. The right sidebar's user filter already uses a friendly matching algorithm: the query is split on whitespace, and each query word must match the *start of some word* in the candidate string, case-insensitively and in any order.

The left sidebar filters do not work this way today. In particular, the topic filter currently treats the query as a comma-separated list of terms and matches each term as a plain substring anywhere in the topic name (e.g. the query `b,d` is treated as two independent substring searches for `b` and `d`).

## Required behavior

Bring the left sidebar topic, DM, and channel filters in line with the right sidebar user filter's matching algorithm:

1. The query is split into words on whitespace. Commas are no longer query separators; they are ordinary characters.
2. A candidate (topic name, DM recipient list, channel name) matches when **every** word of the query matches the **beginning of some word** of the candidate.
3. Matching is case-insensitive.
4. Query words may match candidate words **in any order** — a query does not have to list its words in the order they appear in the candidate.
5. Matches must be at word starts only; a query word that only occurs in the middle of a candidate word is not a match.
6. Non-alphanumeric characters in the candidate are matched literally. A word that begins with punctuation (e.g. `(Project` in `Work (Project A)`) can be matched by a query word that starts with that punctuation.

The filters should only change *which* items are shown, not how they are ordered or counted: the existing ordering of the topic list (most recently active topics first) and the existing summary information (unread counts, counts of possible matches, etc.) must continue to be computed over the filtered set exactly as before.

Existing special cases must keep working. In particular, the empty-string topic name, which is displayed under a localized placeholder name ("general" in English), must still be found when the user types its display name into the topic filter.

## Concrete examples (topic filter, given topics `Backend Developer`, `Developer Backend`, `Work (Project A)`, `authentication flow`, `backend deployment guide`)

- Query `b d` matches both `Backend Developer` and `Developer Backend` (each query word prefix-matches a word; order irrelevant).
- Query `BACKEND` matches both `Backend Developer` and `Developer Backend` (case-insensitive). Their relative order in the results is still determined by recent activity, not by the match.
- Query `Work (` matches `Work (Project A)` — `Work` prefix-matches `Work`, and `(` prefix-matches the word `(Project`.
- Query `auth` matches `authentication flow`, but query `thent` matches nothing — mid-word substrings do not match.
- Queries `ba de gu` and `gu ba de` both match `backend deployment guide` — same words, any order.

## Scope notes

- Apply the same algorithm to the DM filter and the channel-name filter in the left sidebar, matching against DM recipient names and channel names respectively, with identical semantics to the topic filter and the right sidebar user search.
- The codebase already contains shared query-matching utilities used by the right sidebar user search (in the typeahead/people-matching helpers); prefer reusing those rather than writing a new matcher, so all sidebars stay consistent.
