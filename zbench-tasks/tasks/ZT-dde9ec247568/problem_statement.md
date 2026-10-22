# GitHub webhook integration: support additional pull-request sub-events

## Background

Zulip's GitHub webhook integration (`zerver/webhooks/github/view.py`) receives `pull_request` events from GitHub and posts notification messages to a stream. Each `pull_request` payload carries an `action` field (e.g. `opened`, `closed`, `assigned`). Today, several actions are deliberately silenced via an `IGNORED_PULL_REQUEST_ACTIONS` list in the view module: when one of those actions arrives, the integration posts nothing.

We want the integration to produce useful notifications for these currently-ignored (or poorly handled) sub-events:

- `converted_to_draft`
- `review_request_removed`
- `labeled` / `unlabeled`
- `milestoned` / `demilestoned`
- `enqueued` / `dequeued`
- `reopened` (currently handled, but the message lacks branch information)

The `IGNORED_PULL_REQUEST_ACTIONS` list should be removed, with each action either handled with a message template or explicitly treated as a no-op through the integration's normal mechanism for unsupported events. Message templates should follow the style of the existing shared templates in `zerver/lib/webhooks/git.py`.

In the message formats below, `{sender}` is the login of the user who triggered the event (rendered the same way existing PR messages render the actor), `{number}` and `{title}` come from the pull request, and the PR link target is the pull request's `html_url`.

## Interface requirements

- The integration stops ignoring the `converted_to_draft` action and posts: `{sender} converted [PR #{number} {title}]({pr_html_url}) to a draft.`
- The integration stops ignoring the `review_request_removed` action and posts: `{sender} unassigned {requested_reviewer_login} from [PR #{number} {title}]({pr_html_url}).` — where `{requested_reviewer_login}` identifies the reviewer named in the payload's `requested_reviewer` object.
- The integration stops ignoring the `labeled` and `unlabeled` actions and posts: `{sender} added the label \`{label_name}\` on [PR #{number}]({pr_html_url}).` for `labeled`, and `{sender} removed the label \`{label_name}\` from [PR #{number}]({pr_html_url}).` for `unlabeled`. The label name is wrapped in backticks, and these two messages omit the PR title from the link text (link text is just `PR #{number}`).
- The integration handles the `milestoned` and `demilestoned` actions, posting: `{sender} linked [PR #{number}]({pr_html_url}) to the milestone \`{milestone_title}\`.` for `milestoned`, and `{sender} unlinked [PR #{number}]({pr_html_url}) from the milestone \`{milestone_title}\`.` for `demilestoned`. For `milestoned`, the milestone title is read from `pull_request.milestone.title`; for `demilestoned`, it is read from the top-level `milestone` object in the payload (the PR object no longer carries the milestone once it has been removed). Both messages omit the PR title from the link text.
- The integration handles the `enqueued` and `dequeued` actions (merge-queue events), posting: `{sender} added [PR #{number} {title}]({pr_html_url}) to the merge queue.` and `{sender} removed [PR #{number} {title}]({pr_html_url}) from the merge queue.` respectively.
- Messages for `reopened` pull requests include the source and destination branch labels (the payload's `head` and `base` labels, e.g. ``from `owner:feature-branch` to `owner:main` ``), formatted the same way the existing `opened` and `merged` PR messages already include them.
- All of these notifications go to the integration's existing per-PR topic convention (e.g. `{repo} / PR #{number} {title}`), unchanged from current behavior.

## Additional expectations

- These events must respect the integration's existing event-filtering mechanism (the `branches` / included-events URL parameters behave for the new sub-events the same way they do for other pull-request sub-events).
- Payloads for these sub-events follow GitHub's standard webhook schema: top-level `action`, `number`, `pull_request`, `sender`, `repository`, plus `label` for label events, `milestone` for `demilestoned`, and `requested_reviewer` for `review_request_removed`.
- Sub-events not listed above that previously relied on `IGNORED_PULL_REQUEST_ACTIONS` (e.g. `auto_merge_enabled`, `synchronize`, if present in the current list) must continue to produce no message, without raising errors, using the integration framework's standard way of declaring events as intentionally unsupported.

## Acceptance criteria

Sending a GitHub `pull_request` webhook payload with each action listed above to the integration endpoint results in exactly one Zulip message with the corresponding content and topic described under Interface requirements; no action listed above is silently dropped, and the `IGNORED_PULL_REQUEST_ACTIONS` list no longer exists in `zerver/webhooks/github/view.py`.
