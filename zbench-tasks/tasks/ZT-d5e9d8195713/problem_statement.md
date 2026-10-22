# GitLab webhook integration: support Resource Access Token expiry events

## Background

Zulip's GitLab webhook integration (`zerver/webhooks/gitlab/`) handles many GitLab event types, but it does not currently support GitLab's resource access token events. When GitLab sends a notification that a project or group access token is about to expire, the integration does not produce a Zulip notification for it. Organizations relying on these notifications currently get nothing in Zulip when a token is nearing expiry.

## Current behavior

When GitLab delivers a webhook request with the `X-GitLab-Event` HTTP header set to `Resource Access Token Hook`, the integration does not recognize the event and produces no notification message (the event is ignored or rejected as unsupported).

## Required behavior

The integration must handle GitLab "Resource Access Token Hook" events and post a notification message to the configured stream.

### Payload shape

GitLab sends these events with `X-GitLab-Event: Resource Access Token Hook`. The JSON payload has:

- `object_kind`: `"access_token"`
- `event_name`: `"expiring_access_token"`
- `object_attributes`: an object containing at least `name` (the token's name, e.g. `"acd"`) and `expires_at` (the expiry date as a `YYYY-MM-DD` string, e.g. `"2024-01-26"`), along with other fields such as `user_id`, `id`, and `created_at`.
- Exactly one of:
  - `project`: the standard GitLab project object (includes `name`, `web_url`, `path_with_namespace`, etc.) — for project access tokens; or
  - `group`: an object with `group_name`, `group_path`, `group_id`, and `full_path` — for group access tokens.

### Message content

For an expiring access token, the notification message body must be exactly:

```
The access token [{name}]({url}) will expire on {date}.
```

where:

- `{name}` is `object_attributes.name`, rendered as a Markdown link.
- `{url}` points to the resource's access-token settings page:
  - For a **project** token: `{project.web_url}/-/settings/access_tokens` (e.g. `https://example.com/flightjs/Flight/-/settings/access_tokens`).
  - For a **group** token: `https://gitlab.com/groups/{group.group_path}/-/settings/access_tokens` (e.g. for `group_path` `twitter`: `https://gitlab.com/groups/twitter/-/settings/access_tokens`).
- `{date}` is `object_attributes.expires_at` reformatted from `YYYY-MM-DD` into abbreviated-month style `%b %d, %Y` — for example `2024-01-26` renders as `Jan 26, 2024`.

Concrete examples:

- Project token named `acd` on project "Flight" (`web_url` `https://example.com/flightjs/Flight`) expiring `2024-01-26` produces:
  `The access token [acd](https://example.com/flightjs/Flight/-/settings/access_tokens) will expire on Jan 26, 2024.`
- Group token named `acd` on group "Twitter" (`group_path` `twitter`) expiring `2024-01-26` produces:
  `The access token [acd](https://gitlab.com/groups/twitter/-/settings/access_tokens) will expire on Jan 26, 2024.`

### Topic

The Zulip topic for the notification must be:

- the group's `group_name` (e.g. `Twitter`) when the payload contains a `group` object;
- otherwise the project's name (e.g. `Flight`), following the integration's usual project-name topic behavior (including honoring the `use_merge_request_title`-independent standard topic logic and any user-specified topic override, consistent with other GitLab events).

## Interface requirements

- The GitLab webhook integration must handle the GitLab event delivered with the `X-GitLab-Event` header `Resource Access Token Hook` (payload has `object_kind` `"access_token"` and `event_name` `"expiring_access_token"`), producing a Zulip notification message instead of ignoring or erroring on the event.
- The notification message for an expiring resource access token must be exactly: `The access token [{name}]({url}) will expire on {date}.`, where `{name}` is the payload's `object_attributes.name` rendered as a Markdown link.
- The link `{url}` must point to the resource's access-token settings page: for a project token, `{project.web_url}/-/settings/access_tokens`; for a group token, `https://gitlab.com/groups/{group.group_path}/-/settings/access_tokens`.
- The expiry `{date}` must be the payload's `object_attributes.expires_at` (format `YYYY-MM-DD`) reformatted as abbreviated-month style `%b %d, %Y` (e.g. `2024-01-26` becomes `Jan 26, 2024`).
- The Zulip topic for the notification must be the group's `group_name` when the payload contains a `group` object, and otherwise the project's name.

## Notes

- Follow the existing structure of the GitLab webhook handler (`zerver/webhooks/gitlab/view.py`): event types are dispatched by the `X-GitLab-Event` header value to per-event message-body functions, and the topic is derived per event type. Add the new event alongside the existing ones in the same style.
- The new event name should be included in the set of events the integration advertises as supported, consistent with how other GitLab events are registered.
- Only the `expiring_access_token` event name needs to produce this message; the handler is dispatched off the `Resource Access Token Hook` header.
