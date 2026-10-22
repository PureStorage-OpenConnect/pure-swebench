# Add an option to include the repository name in GitHub webhook push notifications

## Background

Zulip's GitHub webhook integration (`zerver/webhooks/github/`) posts notification messages when GitHub sends events such as pushes. Organizations that receive webhook traffic from many repositories into the same channel/topic currently cannot tell, at a glance, which repository a push notification refers to: the first line of a push message names only the pusher, the compare URL, the commit count, and the branch, e.g.

```
baxterthehacker [pushed]( 1 commit to branch changes.
```

The reader has to hover over the commit links to discover the repository.

## Required behavior

Add an opt-in URL option to the GitHub webhook integration that makes push-event messages name and link the repository.

1. **New query parameter.** The integration's webhook URL accepts a new boolean query parameter `include_repository_name`. It is parsed as a JSON boolean (e.g. `include_repository_name=true`) and defaults to false when absent. It is appended to the generated/configured webhook URL in the same manner as existing options of this integration such as `ignore_private_repositories`, and should be documented alongside them in the integration's docs and URL-options metadata as appropriate.

2. **Push message format when enabled.** When `include_repository_name` is true, the first line of a push-event notification changes from:

   `{user} [pushed]({compare_url}) {N} commit(s) to branch {branch}.`

   to:

   `{user} [pushed]({compare_url}) {N} commit(s) to branch {branch} of [{repository_full_name}]({repository_html_url}).`

   That is, ` of ` followed by a Markdown link is inserted before the terminating period. The link text is the repository's full name taken from the GitHub payload's `repository.full_name` field (e.g. `baxterthehacker/public-repo`), and the link target is the repository's HTML URL from the payload's `repository.html_url` field.

   Concrete examples of complete first lines with the option enabled:

   - Single commit:
     `baxterthehacker [pushed]( 1 commit to branch changes of [baxterthehacker/public-repo](
   - Multiple committers (note the committers summary still follows on the same line, after the period):
     `baxterthehacker [pushed]( 6 commits to branch changes of [baxterthehacker/public-repo]( Commits by Tomasz (3), Ben (2) and baxterthehacker (1).`

3. **Everything else is unchanged.** The rest of the message body is not affected by the option: the bulleted commit list (`* Update README.md ([0d1a26e67d8]( the truncation note for long pushes (`[and 30 more commit(s)]`), and the `Commits by X (n), Y (m) and Z (k).` committers detail all render exactly as they do today. The message topic is also unchanged.

4. **Backward compatibility.** When the parameter is absent or false, push messages must be byte-identical to the current format. Other event types (commit comments, issues, PRs, etc.) are unaffected by this option.

Note that push-message formatting for git-hosting integrations is shared via common helpers in `zerver/lib/webhooks/git.py`; other integrations that use those helpers must continue to produce their current output. Only the GitHub integration exposes the new option.

## Interface requirements

- The GitHub webhook integration URL gains a new boolean query parameter named `include_repository_name` (parsed as JSON bool, e.g. `include_repository_name=true`; default false). It is appended to the webhook URL like existing options such as `ignore_private_repositories`.
- When `include_repository_name` is enabled, the push-event notification message's first line changes from '{user} [pushed]({compare_url}) {N} commit(s) to branch {branch}.' to '{user} [pushed]({compare_url}) {N} commit(s) to branch {branch} of [{repository_full_name}]({repository_html_url}).' — i.e. a Markdown link whose text is the repository's full name (from the payload's `repository.full_name`) and whose target is the repository's HTML URL (from the payload's `repository.html_url`). The rest of the message (commit list, truncation note, 'Commits by X (n), ...' committers detail) is unchanged.
- When the option is absent or false, push messages are byte-identical to the pre-existing format (existing tests must keep passing).
