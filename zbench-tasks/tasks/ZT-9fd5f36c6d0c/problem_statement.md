# Add an option to ignore private-project activity in the GitLab webhook integration

## Background

Zulip's GitLab webhook integration (`zerver/webhooks/gitlab/`) receives GitLab webhook events and posts corresponding messages to Zulip channels. GitLab webhook payloads include a `project` object describing the project the event occurred in; that object carries a `visibility_level` field, where the value `0` means the project is **private** (values `10` and `20` mean internal and public, respectively).

## Current behavior

The integration posts messages for all incoming events regardless of the project's visibility. There is no way for an administrator to configure the webhook URL so that activity originating from private GitLab projects is suppressed. As a result, sensitive information from private repositories (commit messages, merge-request titles/descriptions, etc.) can be posted into Zulip channels unintentionally. Zulip's GitHub integration has an equivalent option for skipping private-repository activity; GitLab needs the same capability.

## Required behavior

Add an opt-in filter to the GitLab webhook endpoint that silently drops events from private projects.

1. The GitLab webhook URL accepts a new optional boolean query parameter named `ignore_private_projects` (e.g. `.../api/v1/external/gitlab?api_key=...&stream=...&ignore_private_projects=true`). It defaults to false/absent, preserving today's behavior exactly.
2. When `ignore_private_projects=true` and an incoming event's payload indicates the project is private (the payload's project `visibility_level` equals `0`), the endpoint must **not** send any Zulip message for that event. The request must still be handled as a success from GitLab's perspective: the endpoint returns a normal HTTP 200 success response (the standard "no message was sent" success case used by other webhook filters, not an error), so GitLab does not see delivery failures or retry.
3. When the parameter is false or absent, or when the event's project is not private (or the payload carries no visibility information), events are processed and messages are sent exactly as before.
4. The filter must apply uniformly to every GitLab event type whose payload carries the project visibility information — including, at minimum, push events (`Push Hook`) and merge-request events (`Merge Request Hook`). Note that GitLab payloads for some event types nest project data differently (e.g. a top-level `project` object vs. other locations such as `object_attributes.target`); the check should use the payload's project visibility wherever the integration can determine it for that event type. Concretely: a push event or a merge-request-merged event describing a project with `visibility_level: 0` must produce no message when the option is enabled.
5. Update the GitLab integration documentation (`zerver/webhooks/gitlab/doc.md`) to mention the new URL option, consistent with how comparable options are documented for other integrations.

## Interface requirements

- The GitLab webhook URL gains a boolean query parameter `ignore_private_projects` (e.g. `?ignore_private_projects=true`): when set to true, events from private GitLab projects (payload project `visibility_level == 0`, i.e. private) are silently ignored — the endpoint returns success but sends no message.
- The ignore behavior applies to all event types carrying project visibility info, including push events and merge-request events (the shipped fixtures `push_hook` and `merge_request_hook__merge_request_merged` describe private projects and must produce no message when the option is enabled).

## Acceptance criteria

- A push-event payload for a private project (`visibility_level: 0`) sent to a URL with `ignore_private_projects=true` results in an HTTP success response and no message posted.
- A merge-request-merged payload for a private project sent to a URL with `ignore_private_projects=true` results in an HTTP success response and no message posted.
- The same payloads sent without the parameter (or with it set to false) produce the same messages the integration produces today.
- Events from non-private projects are unaffected by the parameter.
