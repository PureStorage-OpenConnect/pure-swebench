# Replace GitHub usernames with Zulip silent mentions in GitHub integration messages

## Background

Zulip's GitHub webhook integration (`zerver/webhooks/github/`) posts messages that reference event actors by their GitHub login. For example, an issue-comment event currently produces a message like:

```
baxterthehacker [commented]( on [issue](

~~~ quote
You are totally right! I'll get this fixed right away.
~~~
```

Here `baxterthehacker` is the plain GitHub login of the commenter, taken from the webhook payload.

Separately, every Zulip realm ships with a default custom profile field named **"GitHub username"** (an external-account field of subtype `github`), which users can fill in on their profile to record their GitHub login.

## Required behavior

When the GitHub integration renders a message that displays a sender's GitHub login, it should try to map that login to a Zulip user in the recipient realm via the "GitHub username" custom profile field:

1. **Exactly one user in the realm** has the "GitHub username" custom profile field set to the GitHub login from the payload: replace the plain login in the message with a **silent mention** of that Zulip user.
   - The silent mention must use Zulip's canonical form `@_**{full_name}|{user_id}**` (i.e., the output of the pre-existing `silent_mention_syntax_for_user` helper in `zerver/lib/mention.py`), **not** the bare `@_**name**` variant without the user ID.
   - Example: if user Hamlet (full name "King Hamlet", user ID 10) has set the field to `baxterthehacker`, the issue-comment message above becomes:

     ```
     @_**King Hamlet|10** [commented]( on [issue](

     ~~~ quote
     You are totally right! I'll get this fixed right away.
     ~~~
     ```

2. **Zero users, or more than one user** in the realm have that field set to that login (no match, or ambiguous match): display the plain GitHub login unchanged, exactly as today.

3. Everything else about the message must stay **byte-for-byte identical** to the current format — the action link, the issue link, the quoted comment body, and the message topic are unchanged. Only the sender-name token at the start of the message is affected.

Apply this at least to the `issue_comment` event's sender display, and more broadly wherever GitHub logins are displayed in the integration's messages where doing so is straightforward.

## Design constraint

The lookup that resolves an external username (via a custom profile field) to a unique Zulip user must be implemented as a **generic, reusable helper** — placed in shared/common code (not GitHub-webhook-specific code) — so other integrations (GitLab, Bitbucket, etc.) can later reuse it with their own external-account fields. It should take enough parameters (e.g., realm, field, external username) to be integration-agnostic, and should return no match when the username is not set for exactly one user.

## Interface requirements

- When a GitHub webhook message displays a sender's GitHub login, and exactly one user in the realm has the 'GitHub username' custom profile field (the pre-existing default github external-account field) set to that login, the sender name is replaced by a silent mention of that Zulip user.
- The silent mention must use Zulip's canonical `@_**{full_name}|{user_id}**` form (i.e., the output of the pre-existing `silent_mention_syntax_for_user` helper), not the bare `@_**name**` variant.
- If multiple users in the realm have that field set to the same GitHub login (ambiguous match), fall back to displaying the plain GitHub login unchanged.
- The rest of the message (action link, issue link, quoted comment body, topic) keeps the existing issue_comment format byte-for-byte.
