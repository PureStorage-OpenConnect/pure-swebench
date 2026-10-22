# GitLab webhook integration: support emoji events on design comments

## Background

GitLab can send "Emoji Hook" webhook events when a user adds or removes an emoji reaction (an "award") on an awardable object. These payloads have `object_kind: "emoji"` and `event_type` of either `"award"` or `"revoke"`. The Zulip GitLab webhook integration (`zerver/webhooks/gitlab/`) already handles emoji events for common awardables, including comments on merge requests, using message wording of the form:

- award: `<user full name> added the emoji :<emoji name>: to [a comment](<url>).`
- revoke: `<user full name> removed the emoji :<emoji name>: from [a comment](<url>).`

## Problem

Emoji events whose awardable is a **comment on a design** (GitLab Design Management) are not handled. These payloads look like:

- `object_attributes.awardable_type` is `"Note"`
- `object_attributes.awarded_on_url` is `null` (GitLab does not supply a direct URL for these)
- `note.noteable_type` is `"DesignManagement::Design"`
- `note.url` is `null`; the comment's location must be derived from the note payload, notably `note.position.new_path` (e.g. `"designs/issue-1/Sample.png"`, which encodes the parent issue number and the design filename) and `note.id`

When such a payload arrives today, the integration fails to produce a notification message for it.

## Required behavior

Extend the GitLab webhook's emoji-event handling so that award and revoke events on design comments produce messages:

1. **Topic**: `<repository name> / design <design filename>` — the same topic format already used by the integration for note events on designs. Note there is deliberately no `#` before the design name, since designs are identified by filename rather than numeric ID. Example: `sample / design Sample.png`.

2. **Message body**: reuse the existing emoji-event wording (`added the emoji :<name>: to [a comment](<url>).` / `removed the emoji :<name>: from [a comment](<url>).`), where `<url>` is the design comment's URL constructed the same way the integration already constructs URLs for design-comment note events: `<project web_url>/-/issues/<issue number>/designs/<design filename>#note_<note id>`. The issue number and design filename come from `note.position.new_path`.

3. **Custom topic**: when the webhook URL includes a `topic=` query parameter, emoji award/revoke events (including the already-supported merge-request-comment case) must use that topic and prefix the message body with a repository link in the form `[[<repository name>](<project web_url>)] `. This existing behavior must be preserved.

### Concrete examples

Given an `award` payload from project `sample` (web URL `https://gitlab.com/kolanuvarun/sample`) where user `Varun Kolanu` reacts with `heart` on a design comment with note id `2421525600` and `note.position.new_path` = `designs/issue-1/Sample.png`, the integration must send to topic `sample / design Sample.png` the message:

> Varun Kolanu added the emoji :heart: to [a comment](https://gitlab.com/kolanuvarun/sample/-/issues/1/designs/Sample.png#note_2421525600).

Given a `revoke` payload for an emoji on a merge request comment from the same project, delivered to a webhook URL with `topic=notifications`, the integration must send to topic `notifications` a message like:

> [[sample](https://gitlab.com/kolanuvarun/sample)] Varun Kolanu removed the emoji :heart: from [a comment](https://gitlab.com/kolanuvarun/sample/-/merge_requests/1#note_2431339003).

## Sample payload

Following the integration framework's convention of documenting each supported sub-event with a captured example payload, add `zerver/webhooks/gitlab/fixtures/emoji_hook__award__design_note.json` (naming convention: `<object_kind>_hook__<event_type>__<awardable subtype>`). It must be a realistic GitLab Emoji Hook payload matching the award example above, with at least: `object_kind: "emoji"`, `event_type: "award"`; `user.name: "Varun Kolanu"`; a `project` block with `name: "sample"` and `web_url: "https://gitlab.com/kolanuvarun/sample"`; `object_attributes` with `name: "heart"`, `awardable_type: "Note"`, `awardable_id: 2421525600`, `awarded_on_url: null`; and a `note` block with `id: 2421525600`, `noteable_type: "DesignManagement::Design"`, `url: null`, and `position.new_path: "designs/issue-1/Sample.png"`. (A revoke fixture for merge-request comments already exists as `emoji_hook__revoke__merge_request_note`.)

## Interface requirements

- The GitLab webhook integration must handle Emoji Hook award/revoke events whose awardable is a comment on a design (payload has `object_attributes.awardable_type = "Note"` and `note.noteable_type = "DesignManagement::Design"`, with `object_attributes.awarded_on_url` null); at present such payloads are not handled.
- For emoji events on design comments, the Zulip topic must be `<repo name> / design <design filename>` (e.g. `sample / design Sample.png`), matching the topic format already used for design-comment note events; no `#` sign precedes the design name, since designs are identified by filename rather than numeric ID.
- For emoji events on design comments, the message must follow the existing emoji-event wording — `<user full name> added the emoji :<emoji name>: to [a comment](<url>).` for award (`removed ... from` for revoke) — where `<url>` is the design comment's URL derived from the note payload the same way as for existing design-comment events: `<project web_url>/-/issues/<issue>/designs/<design filename>#note_<note id>`.
- When the webhook URL includes a custom `topic=` parameter, emoji award/revoke events must continue to use that topic and prefix the message with the repository link in the form `[[<repo name>](<project web_url>)] ` (existing include-title behavior must be preserved for emoji events on merge request comments).
