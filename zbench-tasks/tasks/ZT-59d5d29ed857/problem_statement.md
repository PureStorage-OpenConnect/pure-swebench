# Support GitLab design-comment note events in the GitLab webhook integration

## Background

Zulip's GitLab integration (`zerver/webhooks/gitlab/`) processes GitLab webhook payloads and posts formatted messages to a Zulip stream. GitLab sends a `note` event (`object_kind: "note"`, `event_type: "note"`) whenever someone comments on various objects. The integration currently dispatches note events based on the noteable type and supports comments on commits, merge requests, issues, and snippets.

GitLab also lets users comment on **designs** (images attached to issues via GitLab's Design Management feature). When someone comments on a design, GitLab sends a note event whose `object_attributes.noteable_type` is `"DesignManagement::Design"`. The integration does not recognize this noteable type, so the webhook request fails with HTTP 400 (unsupported event) instead of producing a message.

An example payload for a design comment:

```json
{
    "object_kind": "note",
    "event_type": "note",
    "user": {
        "id": 14613894,
        "name": "Satyam Bansal",
        "username": "sbansal1999",
        "avatar_url": "https://gitlab.com/uploads/-/system/user/avatar/14613894/avatar.png",
        "email": "[REDACTED]"
    },
    "project_id": 46186758,
    "project": {
        "id": 46186758,
        "name": "testing-zulip-gitlab-integration",
        "web_url": "https://gitlab.com/sbansal1999/testing-zulip-gitlab-integration",
        "path_with_namespace": "sbansal1999/testing-zulip-gitlab-integration",
        "default_branch": "main",
        "homepage": "https://gitlab.com/sbansal1999/testing-zulip-gitlab-integration"
    },
    "object_attributes": {
        "author_id": 14613894,
        "commit_id": null,
        "created_at": "2023-07-05 16:38:53 UTC",
        "discussion_id": "90c3bd62a51e132229eb2433a42af0707c1b7091",
        "id": 1458583152,
        "note": "hello",
        "noteable_id": 601586,
        "noteable_type": "DesignManagement::Design",
        "position": {
            "base_sha": "0000000000000000000000000000000000000000",
            "start_sha": "0000000000000000000000000000000000000000",
            "head_sha": "3e8137cae02e78675cd220ae1dd2ced26feba62f",
            "old_path": null,
            "new_path": "designs/issue-1/Screenshot.png",
            "position_type": "image",
            "width": 740,
            "height": 499,
            "x": 413,
            "y": 315
        },
        "system": false,
        "type": "DiffNote",
        "updated_at": "2023-07-05 16:38:53 UTC",
        "description": "hello",
        "url": null
    },
    "repository": {
        "name": "testing-zulip-gitlab-integration",
        "url": "git@gitlab.com:sbansal1999/testing-zulip-gitlab-integration.git",
        "homepage": "https://gitlab.com/sbansal1999/testing-zulip-gitlab-integration"
    }
}
```

Note two things about this payload that make it different from other note events: `object_attributes.url` is `null` (GitLab does not supply a direct link to the comment), and there is no `issue` field — the only clue to which issue the design belongs to is the `position.new_path` value, which has the form `designs/issue-{N}/{filename}`.

## Required behavior

When the GitLab integration receives a note event with `object_attributes.noteable_type` of `"DesignManagement::Design"` (a confidential variant of this noteable type must be handled the same way, matching how the integration already pairs confidential variants for issues), it must accept the request (HTTP 200) and post a message as follows.

Derived values:

- **Design filename**: the last path segment of `object_attributes.position.new_path`. For `"designs/issue-1/Screenshot.png"` this is `Screenshot.png`.
- **Issue number**: parsed from the same path, which has the form `designs/issue-{N}/{filename}` — here `1`.
- **Design URL**: because the payload contains no direct URL, construct it as `{repository homepage}/-/issues/{issue number}/designs/{design filename}`, e.g. `https://gitlab.com/sbansal1999/testing-zulip-gitlab-integration/-/issues/1/designs/Screenshot.png`.
- **Comment URL**: the design URL with `#note_{object_attributes.id}` appended, e.g. `https://gitlab.com/sbansal1999/testing-zulip-gitlab-integration/-/issues/1/designs/Screenshot.png#note_1458583152`.

Message formatting:

- **Topic**: `{repository name} / design {design filename}` — for the sample payload: `testing-zulip-gitlab-integration / design Screenshot.png`.
- **Message body**: `{commenter's display name} [commented]({comment URL}) on design [{design filename}]({design URL}):` followed by a blank line and the note text in the integration's standard quote block:

```
Satyam Bansal [commented](https://gitlab.com/sbansal1999/testing-zulip-gitlab-integration/-/issues/1/designs/Screenshot.png#note_1458583152) on design [Screenshot.png](https://gitlab.com/sbansal1999/testing-zulip-gitlab-integration/-/issues/1/designs/Screenshot.png):

~~~ quote
hello
~~~
```

The integration's existing generic behaviors must continue to apply to this event type. In particular, when the webhook URL specifies a fixed topic (the `topic` query parameter), the message goes to that topic and the body is prefixed with the standard bracketed repository link, producing for the sample payload:

```
[[testing-zulip-gitlab-integration](https://gitlab.com/sbansal1999/testing-zulip-gitlab-integration)] Satyam Bansal [commented](https://gitlab.com/sbansal1999/testing-zulip-gitlab-integration/-/issues/1/designs/Screenshot.png#note_1458583152) on design [Screenshot.png](https://gitlab.com/sbansal1999/testing-zulip-gitlab-integration/-/issues/1/designs/Screenshot.png):

~~~ quote
hello
~~~
```

## Interface requirements

- The GitLab webhook integration must handle note events whose `object_attributes` `type`/`noteable_type` indicates a design comment (`noteable_type` `"DesignManagement::Design"`, including the confidential variant) instead of failing as an unsupported event.
- For design comments, the Zulip topic must be `{repository name} / design {design filename}`, where the design filename is the last path segment of `object_attributes.position.new_path` (e.g. `testing-zulip-gitlab-integration / design Screenshot.png`).
- Since design-note payloads carry no direct issue field or comment URL, the design's web URL must be constructed as `{repository homepage}/-/issues/{issue number}/designs/{design filename}`, where the issue number is parsed from the `position.new_path` of the form `designs/issue-{N}/{filename}`.
- The comment URL must be the design URL with the anchor `#note_{object_attributes.id}` appended.
- The message body for a design comment must be `{commenter's display name} [commented]({comment URL}) on design [{design filename}]({design URL}):` followed by the note text rendered in the integration's standard quote block (`~~~ quote\n{note}\n~~~`).
