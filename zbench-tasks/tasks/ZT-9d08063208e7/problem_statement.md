# GitHub integration: handle issue transfers correctly

## Background

Zulip's incoming GitHub webhook integration (`zerver/webhooks/github/`) posts notification messages when GitHub sends `issues` events. GitHub supports transferring an issue from one repository to another. A transfer produces webhook traffic that the integration currently mishandles.

## Current (incorrect) behavior

When an issue is transferred into a repository, GitHub delivers an `issues` event with `"action": "opened"` to the destination repository's webhook. The integration treats this like any newly opened issue and posts something like:

> alya opened [issue Ask user about deleting uploaded files when removed from message](…)
> [… full issue description quoted …]

This is wrong in several ways:

* The issue was not opened today — it was transferred. The verb should reflect the transfer.
* The named actor is the issue's original author, not the person who performed the transfer.
* Quoting the full issue description is noisy (bulk transfers during a repo migration would produce very bulky messages), and the description contains nothing new.
* The message doesn't say which repository the issue came from.

Separately, GitHub also delivers an `issues` event with `"action": "transferred"` (to the source repository's webhook). The integration should produce a useful notification for this action as well.

## Payload shapes

Both event variants can be distinguished from a normal issue-opened event by the presence of a `changes` object in the payload:

1. **`action: "transferred"`** — the top-level `issue` object describes the *old* issue (in the source repository), and the payload contains `changes.new_issue` (the issue as recreated in the destination repository, including `number` and `html_url`) and `changes.new_repository` (including `full_name`). The top-level `sender` is the user who performed the transfer.

2. **`action: "opened"` with `changes.old_issue`** — the top-level `issue` object describes the *new* issue in the destination repository (its `created_at` is the original creation date, and `user` is the original author — which is why the current message is misleading). The payload contains `changes.old_issue` (the issue as it existed in the source repository) and `changes.old_repository` (including `full_name`). An `action: "opened"` payload with no `changes.old_issue` is a genuine newly-opened issue and must keep the existing behavior.

Collect/keep representative example payloads for both variants so the exact field paths above are exercised.

## Required behavior

### 1. `issues` event, action `transferred`

Post the message body (exact format, including trailing period):

```
{sender} transferred [issue #{old_issue_number} {title}]({old_issue_html_url}) to [{new_repo_full_name}/#{new_issue_number}]({new_issue_html_url}).
```

where `{sender}` is the login of the payload's `sender`; the old issue number, title, and HTML URL come from the payload's top-level `issue`; and the new repository full name, new issue number, and new issue HTML URL come from `changes.new_repository` and `changes.new_issue` respectively.

Example: `gnprice transferred [issue Ask user about deleting uploaded files when removed from message]( to [zulip/zulip-flutter/#123](

### 2. `issues` event, action `opened`, payload contains `changes.old_issue`

Instead of the normal issue-opened message (and without quoting the issue description), post the message body (exact format, including trailing period):

```
[Issue #{issue_number} {title}]({issue_html_url}) was transferred from {old_repo_full_name}.
```

using the payload's top-level `issue` fields for the number, title, and HTML URL, and `changes.old_repository.full_name` for the source repository name.

Note there is deliberately no actor named in this message — the payload's `issue.user` is the original author, not the transferrer, so naming them would be misleading.

### Topic

Both messages go to the topic that the integration already uses for issue events:

```
{repo name} / issue #{issue number} {issue title}
```

using the repository and issue that the message is about, following the integration's existing topic-construction code path for issues.

## Interface requirements

* The two cases must be exposed as distinct user-facing event types named `issues_transferred` and `issues_opened_via_transfer` in the GitHub webhook's list of supported events, so that they can be selected or excluded via the webhook URL's event-filtering query parameter (the same mechanism that already lets users filter events like `issues`, `push`, etc.).
* The `issues_transferred` message format: `{sender} transferred [issue #{old_issue_number} {title}]({old_issue_html_url}) to [{new_repo_full_name}/#{new_issue_number}]({new_issue_html_url}).` with fields sourced as described in Required behavior §1.
* The `issues_opened_via_transfer` message format: `[Issue #{issue_number} {title}]({issue_html_url}) was transferred from {old_repo_full_name}.` with fields sourced as described in Required behavior §2.
* Topic for both: `{repo name} / issue #{issue number} {issue title}`, per the integration's existing convention for issue events.

## Acceptance criteria

* An `issues` payload with `action: "transferred"` produces exactly the §1 message on the standard issue topic.
* An `issues` payload with `action: "opened"` that contains `changes.old_issue` produces exactly the §2 message on the standard issue topic, with no issue-description quote.
* An `issues` payload with `action: "opened"` and no `changes.old_issue` behaves exactly as before.
* `issues_transferred` and `issues_opened_via_transfer` appear in the webhook's supported-event list and work with the URL event-filtering parameter.
