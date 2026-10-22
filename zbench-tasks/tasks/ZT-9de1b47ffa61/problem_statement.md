# Improve topic names for imported Slack threads

## Context

Zulip's Slack importer (`zerver/data_import/slack.py` and related modules) converts Slack channels and their messages into Zulip streams, topics, and messages. Slack threads have no direct equivalent in Zulip, so the importer maps each Slack thread to its own Zulip topic within the destination stream.

## Current behavior

Today, each imported Slack thread is given a generated topic name of the form:

```
<YYYY-MM-DD> Slack thread <N>
```

where the date comes from the thread's root message timestamp and `N` is a per-date counter (the first thread started on a given date is `Slack thread 1`, the second on the same date is `Slack thread 2`, and so on).

This is unhelpful: users browsing an imported realm cannot tell what any thread is about from names like `2015-08-18 Slack thread 2`.

## Required behavior

Replace the counter-based scheme with descriptive topic names built from the thread's root message content.

1. **Name format.** Each Slack thread's Zulip topic name must be the root message's date (in UTC, formatted `YYYY-MM-DD`), then a single space, then a snippet of the thread's root message text. Example: a thread whose root message was sent on 2015-06-12 with text `message body text` gets the topic `2015-06-12 message body text`.
2. **Snippet source.** The snippet is taken from the raw message text as it exists at import time — do not strip or re-render Slack markup (e.g. `*foo* _bar_`), user-mention syntax (e.g. `<@U061A1R2R>`), or link syntax before building the snippet.
3. **Truncation.** The full generated topic name must not exceed Zulip's maximum topic length of 60 characters. When the date + snippet would exceed 60 characters, shorten the snippet and end the name with the single Unicode ellipsis character `…` (U+2026) as the truncation marker, such that the resulting name uses the full 60 characters. For example, a root message sent 2015-08-18 with text `random message but it's too long for the thread topic name` produces exactly `2015-08-18 random message but it's too long for the thread …` (60 characters).
4. **Collision handling.** If two or more distinct threads would produce the identical topic name (same date and same snippet), keep the first occurrence unchanged and give each later thread a disambiguating numeric suffix ` (N)` — the second occurrence gets ` (2)`, the third ` (3)`, etc. When adding a suffix would push the name past 60 characters, shorten the snippet further so the complete name including the suffix still fits within the limit.
5. **Thread grouping.** Every message belonging to one Slack thread — the root message plus all replies sharing its `thread_ts`, including replies that carry Slack's `parent_user_id` field — must be placed under that thread's single generated topic name. Replies must never spawn a topic of their own.
6. **No regressions for attachments.** Threaded messages that carry file attachments (Slack `files` entries) must still have their uploads and attachment records produced exactly as they are for non-threaded messages; the new topic-naming logic must not interfere with file handling.

Non-threaded channel messages are unaffected and keep their existing topic behavior.

## Interface requirements

- When importing Slack threads, each thread's Zulip topic name becomes the thread's root-message date (UTC, formatted `YYYY-MM-DD`) followed by a space and a snippet of the thread's root message text, e.g. `2015-06-12 message body text` (replacing the old `<date> Slack thread <N>` scheme).
- The generated topic name is truncated to the maximum Zulip topic length (60 characters), using the single ellipsis character `…` as the truncation marker; a truncated topic must use the full 60 characters.
- When two or more distinct threads would produce the same topic name (same date and same snippet), later threads get a disambiguating numeric suffix ` (N)` (second occurrence ` (2)`, etc.); the snippet is shortened as needed so the name including the suffix still fits within the 60-character limit.
- All messages belonging to one Slack thread (root message and replies sharing its `thread_ts`, including replies carrying Slack's `parent_user_id` field) are placed under that thread's single generated topic name.
- Thread topic snippets are taken from the raw message text as imported; importer output for threaded messages with file attachments must still record the uploads/attachments as for non-threaded messages.
