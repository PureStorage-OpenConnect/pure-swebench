# GitLab webhook integration: support merge-request "approval" and "unapproval" actions

## Background

Zulip's GitLab webhook integration (`zerver/webhooks/gitlab/view.py`) processes GitLab "Merge Request Hook" events. Each merge-request payload carries `object_attributes.action` identifying the sub-event (e.g. `open`, `update`, `merge`, `close`, `approved`, `unapproved`). When a project on GitLab is configured to require multiple approvers, GitLab sends two additional sub-events that are distinct from `approved`/`unapproved`: `action: "approval"` (a single reviewer added their approval, but the MR is not yet fully approved) and `action: "unapproval"` (a reviewer revoked their approval).

## Current behavior

The integration does not recognize the `approval` and `unapproval` actions on merge-request events. Payloads carrying these actions are not turned into notification messages (they are ignored or treated as an unsupported event).

## Required behavior

When the GitLab webhook endpoint receives a `Merge Request Hook` payload (`object_kind: "merge_request"`, `event_type: "merge_request"`) whose `object_attributes.action` is `"approval"` or `"unapproval"`, it must successfully produce a notification message, following the same conventions as the other merge-request sub-events:

- The message must be sent to the same topic that other merge-request events for that MR use: `<repo name> / MR #<iid> <title>` (e.g. `my-awesome-project / MR Update the README`). Topic handling, including the `use_merge_request_title` URL parameter and user-specified topic overrides, must behave the same as for existing merge-request sub-events.
- The message body must follow the existing merge-request message format used elsewhere in the integration (actor in bold, MR rendered as a Markdown link `[MR #<iid> <title>](<object_attributes.url>)`):
  - For `action: "approval"`, the action phrase is **"added their approval for"**, producing e.g.:
    `**Sumit Bhanushali** added their approval for [MR Update the README](https://gitlab.com/sumitb16/my-awesome-project/merge_requests/1).`
  - For `action: "unapproval"`, the action phrase is **"removed their approval for"**, producing e.g.:
    `**Sumit Bhanushali** removed their approval for [MR Update the README](https://gitlab.com/sumitb16/my-awesome-project/merge_requests/1).`
- The actor name comes from the top-level `user.name` field of the payload, as with other merge-request events.
- These messages must not include the branch/description details block that is appended for MR "open" events; they follow the short single-line form used by other state-change actions (approved, closed, merged, etc.).
- The endpoint must return a success response for these payloads; it must not raise an unsupported-event error.

Note that these payloads contain fields the existing handler may not expect: `changes` may be an empty object `{}` and `object_attributes` includes keys such as `approval_rules`, `reviewer_ids`, `draft`, and `detailed_merge_status`. The handler must tolerate these.

## Fixtures

Add one fixture per sub-event under `zerver/webhooks/gitlab/fixtures/`, following the existing naming convention for merge-request fixtures:

- `merge_request_hook__merge_request_approval.json` — a real-shaped GitLab merge-request payload with `object_attributes.action: "approval"`.
- `merge_request_hook__merge_request_unapproval.json` — the same MR payload shape with `object_attributes.action: "unapproval"`.

Each should be a complete GitLab merge-request webhook payload (top-level `object_kind`, `event_type`, `user`, `project`, `object_attributes` with `iid`, `title`, `url`, `source_branch`, `target_branch`, `state`, `action`, plus `labels`, `changes`, `repository`, and `reviewers`).

## Interface requirements

- The GitLab webhook integration must handle merge-request events whose payload has `object_attributes.action` set to `"approval"` or `"unapproval"` (sent by GitLab when a merge request requires multiple approvers), instead of ignoring or erroring on them.
- For an `"approval"` event, the notification message must phrase the action as "added their approval for", e.g. `<user> added their approval for <linked MR>`, following the existing merge-request message format.
- For an `"unapproval"` event, the notification message must phrase the action as "removed their approval for", following the same format.

## Scope

The change is confined to the GitLab webhook integration (`zerver/webhooks/gitlab/`): event handling in `view.py`, any shared message-template helpers it uses (see `zerver/lib/webhooks/git.py` for the existing merge-request templates), and the new fixtures. Behavior of all other GitLab sub-events must be unchanged.
