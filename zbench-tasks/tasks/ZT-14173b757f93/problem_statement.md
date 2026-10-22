# GitHub webhook: support all `discussion` event actions

## Context

Zulip's GitHub webhook integration (`zerver/webhooks/github/`) receives GitHub webhook payloads and converts them into Zulip messages. GitHub sends a `discussion` event for many different actions on a repository discussion: `created`, `edited`, `deleted`, `pinned`, `unpinned`, `locked`, `unlocked`, `labeled`, `unlabeled`, `closed`, `reopened`, `transferred`, `category_changed`, `answered`, and `unanswered`. The payload's top-level `action` field identifies which one occurred.

## Current (buggy) behavior

The handler for `discussion` events (`get_discussion_body` in `zerver/webhooks/github/view.py`) ignores the payload's `action` field and always renders the same "created" template. So when a discussion is answered, closed, locked, etc., the integration posts a message claiming the sender *created* the discussion, with the full discussion body quoted — which is wrong for every action other than `created`.

## Required behavior

The `discussion` event handler must branch on the payload's `action` field and produce an action-appropriate message. All messages go to the same Zulip topic as today: `{repo} discussion #{number}: {title}` (topic naming is unchanged).

Throughout the formats below:

- `{sender}` is rendered with the integration's existing sender-name formatting (the payload `sender.login`, as used by the other GitHub event handlers).
- `{optional title}` means: when the integration's existing include-title option is enabled (the `topic` URL query parameter supplied when configuring the webhook URL), the discussion title is appended after the number inside the link text as ` {title}`; when the option is off, nothing is appended.
- `[discussion #{number}{optional title}]({html_url})` is a Markdown link to the discussion's `html_url` from the payload.
- "Quote block" means Zulip's quoted-message formatting (the same ````` quote ... ````` construct the integration already uses elsewhere).

### Per-action message formats

1. **`created`** — `{sender} created [discussion #{number}]({html_url}) in {category name}:` followed by a quote block containing `### {title}` and then the discussion body. This matches the current created message except the link text now reads `discussion #{number}`. `{category name}` is `discussion.category.name` from the payload.

2. **`unlocked`, `pinned`, `unpinned`, `reopened`** — `{sender} {action} [discussion #{number}{optional title}]({html_url}).` where `{action}` is the raw payload action string.

3. **`deleted`** — `{sender} deleted discussion #{number}{optional title}.` with **no** hyperlink anywhere (the discussion no longer exists, so its URL must not be linked).

4. **`closed`** — `{sender} closed [discussion #{number}{optional title}]({html_url}) as {state_reason}.` where `{state_reason}` is `discussion.state_reason` from the payload (e.g. `resolved`).

5. **`locked`** — `{sender} locked [discussion #{number}{optional title}]({html_url}) as {active_lock_reason}.` using `discussion.active_lock_reason` from the payload. When `active_lock_reason` is null, the entire ` as {reason}` suffix is omitted, yielding `{sender} locked [discussion #{number}{optional title}]({html_url}).`

6. **`labeled`** — `{sender} added the {label name} label to [discussion #{number}{optional title}]({html_url}).` The label name comes from the payload's `label.name`.

7. **`unlabeled`** — `{sender} removed the {label name} label from [discussion #{number}{optional title}]({html_url}).`

8. **`category_changed`** — `{sender} changed the category of [discussion #{number}{optional title}]({html_url}) from {old category name} to {new category name}.` The old category name is read from the payload's `changes` object (the previous category); the new one is the discussion's current category name.

9. **`transferred`** — `{sender} transferred discussion #{old number}{optional title} from {old repository name} to {new repository name} as [discussion #{new number}]({html_url}).` The old number/title/repository describe the discussion in the payload's `discussion`/`repository` fields. The new repository name is `changes.new_repository.name` and the new discussion number is `changes.new_discussion.number`. The link's URL (`{html_url}`) is the **original** discussion's `html_url` (the top-level `discussion.html_url`), **not** the new discussion's URL. Only the new discussion reference is a link.

10. **`answered`** — `{sender} marked [comment #{answer id}]({answer html_url}) as the answer:` followed by a quote block containing the answer comment's body. The answer comment is the payload's top-level `answer` object (its `id`, `html_url`, and `body`).

11. **`unanswered`** — `{sender} marked [comment #{old_answer id}]({old_answer html_url}) as not the answer.` reading the payload's top-level `old_answer` object. No quote block.

12. **`edited`** — two cases, distinguished by the payload's `changes` object:
    - If `changes` contains a `body` key (the body was edited): `{sender} edited [discussion #{number}{optional title}]({html_url}):` followed by a quote block containing the discussion's new body.
    - Otherwise (title edit): `{sender} edited the title of [discussion #{number}{optional title}]({html_url}):` followed by a quote block containing `### {new title}` (the discussion's current title).

All of these actions must be accepted by the existing webhook endpoint and produce a message — none of them may be dropped or raise an "unsupported event" error.

## Payload reference

GitHub's `discussion` webhook payloads always include `action`, `discussion` (with `number`, `title`, `body`, `html_url`, `state_reason`, `active_lock_reason`, `category.name`, etc.), `repository`, and `sender`. Depending on the action they may additionally include `label`, `answer`, `old_answer`, or `changes` (which for `category_changed` holds the old category, for `transferred` holds the new repository and new discussion, and for `edited` holds the old body and/or title). Example fragment of an `answered` payload:

```json
{
  "action": "answered",
  "discussion": { "number": 349, "title": "...", "state": "open", ... },
  "answer": { "id": 6217049, "html_url": "...", "body": "...", ... }
}
```

When adding sample payloads for development, follow the integration's existing fixture-file conventions in `zerver/webhooks/github/fixtures/` (per-action files named `discussion__{action}.json`); a single generic `discussion.json` sample no longer reflects the per-action handling and should be replaced by per-action samples.

## Interface requirements

- The GitHub webhook integration must handle **all** `discussion` event actions listed above (not just `created`), producing Zulip messages via the pre-existing webhook endpoint; topic naming keeps the existing `{repo} discussion #{number}: {title}` format.
- For action `created`, the message is: `{sender} created [discussion #{number}]({html_url}) in {category name}:` followed by a Zulip quote block containing `### {title}` and the discussion body (this matches the pre-existing created-message format except the numbered link now reads `discussion #{number}`).
- For actions `unlocked`, `pinned`, `unpinned`, and `reopened`, the message is: `{sender} {action} [discussion #{number}{optional title}]({html_url}).` where the action verb is the raw payload action.
- For action `deleted`, the message is: `{sender} deleted discussion #{number}{optional title}.` with no hyperlink (the discussion no longer exists).
- For action `closed`, the message is: `{sender} closed [discussion #{number}{optional title}]({html_url}) as {state_reason}.` using the payload's discussion `state_reason` (e.g. `resolved`).
- For action `locked`, the message is: `{sender} locked [discussion #{number}{optional title}]({html_url}) as {active_lock_reason}.`; when `active_lock_reason` is null the entire ` as {reason}` suffix is omitted.
- For actions `labeled`/`unlabeled`, the messages are: `{sender} added the {label name} label to [discussion #{number}{optional title}]({html_url}).` and `{sender} removed the {label name} label from [discussion #{number}{optional title}]({html_url}).`
- For action `category_changed`, the message is: `{sender} changed the category of [discussion #{number}{optional title}]({html_url}) from {old category name} to {new category name}.`
- For action `transferred`, the message is: `{sender} transferred discussion #{old number}{optional title} from {old repository name} to {new repository name} as [discussion #{new number}]({html_url}).` The new repository name is `changes.new_repository.name` and the new discussion number is `changes.new_discussion.number`; the link URL is the **original** discussion's `html_url` (the top-level `discussion.html_url`), **not** the new discussion's URL.
- For action `answered`, the message is: `{sender} marked [comment #{answer comment id}]({answer html_url}) as the answer:` followed by a quote block with the answer comment's body; for `unanswered`, the message is `{sender} marked [comment #{old_answer comment id}]({old_answer html_url}) as not the answer.` (`answered` reads the `answer` payload field, `unanswered` reads `old_answer`).
- For action `edited`: if the payload's `changes` object contains `body`, the message is `{sender} edited [discussion #{number}{optional title}]({html_url}):` followed by a quote block with the new body; otherwise (title edit) it is `{sender} edited the title of [discussion #{number}{optional title}]({html_url}):` followed by a quote block with `### {new title}`.
- `{optional title}` means: when the integration's pre-existing include-title configuration (topic in URL query) is enabled, the discussion title is appended after the number as ` {title}` inside the link text; otherwise it is omitted.
- `{sender}` uses the integration's pre-existing sender-name formatting (the payload sender's login).
