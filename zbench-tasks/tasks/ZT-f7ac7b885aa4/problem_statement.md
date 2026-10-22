# Narrow filtering: `-is:dm` conflicts incorrectly with channel operators

## Context

Zulip's message-fetch API accepts a *narrow*: a list of filter terms, each with an `operator`, an `operand`, and a `negated` flag (rendered in the search UI with a leading `-`, e.g. `-is:dm`). The narrow-building code in `zerver/lib/narrow.py` translates these terms into a SQL query. Because no message can be both a channel (stream) message and a direct message, the builder tracks whether the narrow has restricted results to channel messages or to direct messages, and raises `BadNarrowOperatorError` with the message:

```
Invalid narrow operator: No message can be both a channel message and direct message
```

when a narrow tries to require both at once (surfaced to API clients as an HTTP 400).

## Current (buggy) behavior

The conflict detection ignores the `negated` flag, so it misclassifies negated terms:

1. Searching `channels:public -is:dm` (in either order) yields no results, because `-is:dm` is treated as if it were `is:dm` — i.e., as a direct-message restriction that conflicts with the channel restriction. The user's intent ("public channel messages, excluding DMs") is perfectly satisfiable; excluding DMs is merely redundant here.
2. Similarly, `is:dm -channels:public` is treated as combining a DM restriction with a channel restriction, even though a *negated* channel term does not restrict results to channel messages.
3. Conversely, `-is:dm dm:user@example.com` is currently *not* rejected, even though `-is:dm` means "only channel messages" and a positive `dm:` term means "only direct messages with this user" — a genuinely unsatisfiable combination.

## Required behavior

Make the channel-vs-DM conflict detection respect negation. Semantics: a **positive** `is:dm` (or positive `dm:`/`dm-including:` style term) restricts the narrow to direct messages; a **negated** `is:dm` restricts it to channel messages; a **positive** channel term (`channel:`, `channels:`, `topic:`, etc.) restricts it to channel messages; a **negated** channel term imposes no such restriction.

Concretely:

1. A narrow combining `-is:dm` with `channels:public` (in either order) must build and execute successfully, returning exactly the messages that `channels:public` alone would return.
2. A narrow combining `is:dm` with a negated channel term such as `-channels:public` must also build successfully (no false conflict error).
3. A narrow combining `-is:dm` with a positive direct-message term such as `dm:user@example.com` must be rejected with `BadNarrowOperatorError` whose string form is exactly `Invalid narrow operator: No message can be both a channel message and direct message`.
4. Existing behavior for genuinely conflicting positive combinations (e.g. `is:dm` + `channels:public`, or `dm:...` + `channel:...`) must be unchanged: they continue to raise the same error.

The fix should live in the narrow-building layer so it applies to any API endpoint or UI surface that constructs message queries from narrow terms.
