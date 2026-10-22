# GitHub integration: suppress spurious "edited" messages when a comment is hidden

## Context

Zulip's incoming GitHub webhook integration (`zerver/webhooks/github/`) turns GitHub webhook events into Zulip messages. For the `issue_comment` event with `"action": "edited"`, the bot currently posts a message saying the user "edited a comment" on the issue/PR, including the comment's body.

## Problem

When someone uses GitHub's "hide comment" feature (e.g. marking a comment as outdated, off-topic, or abusive), GitHub sometimes delivers an `issue_comment` webhook with `"action": "edited"` even though the comment's text was not actually changed. The Zulip bot then announces that the comment was "edited" and re-posts its full body.

This is bad behavior: the whole point of hiding a comment is that it is noise, yet the bot repeats it into the Zulip thread with a misleading verb ("edited").

The telltale signature of these events is that the payload's `changes` object reports no real modification: `changes.body.from` (the previous body) is identical to the current `comment.body`. A payload for a genuine edit has a `changes.body.from` value that differs from `comment.body`. (Other `changes` keys such as `changes.title.from` behave analogously for their respective fields.) An example hide-triggered payload looks like a normal `issue_comment` edited payload — with top-level keys `action`, `changes`, `issue`, `comment`, `repository`, `sender` — except that the string under `changes.body.from` exactly matches `comment.body`.

## Required behavior

1. When the GitHub webhook receives an `issue_comment` event with `action: "edited"` whose reported changes indicate the comment content is in fact unchanged (the old value(s) in `changes` equal the corresponding current value(s) on the comment), the integration must not send any Zulip message at all for that event. The webhook endpoint must still accept the request successfully (normal 200-style success response, as with other intentionally-ignored events); it must not raise an error or log it as an unsupported event type.
2. Genuine comment edits — where the previous body in `changes.body.from` differs from the current `comment.body` — must continue to produce the existing "edited a comment" message, unchanged in topic and content from current behavior.
3. Newly created comments (`action: "created"`) and other `issue_comment` actions must be unaffected.

## Acceptance criteria

- Feeding the integration an `issue_comment` payload with `action: "edited"` where `changes.body.from` is byte-for-byte equal to `comment.body` results in zero Zulip messages being sent, and the HTTP request succeeds.
- Feeding it an `issue_comment` payload with `action: "edited"` where the body genuinely changed still produces the usual comment-edited notification message.
- The behavior does not depend on any new user-facing configuration; suppression of these no-op "edited" events is unconditional.

## Notes

- Keep the change scoped to the GitHub webhook integration's handling of `issue_comment` events; do not alter how other event types are routed or filtered.
- Follow the integration's existing convention for events that are deliberately ignored (i.e., handled as a recognized event that produces no message, not treated as an unknown/unsupported event).
