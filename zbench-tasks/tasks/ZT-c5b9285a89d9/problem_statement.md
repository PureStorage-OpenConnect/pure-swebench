# Replace the Redmine plugin integration with an incoming webhook integration

## Background

Zulip currently offers a Redmine integration implemented as a Redmine-side plugin, cataloged as a non-webhook integration. We want to replace it with a proper incoming webhook integration built on Zulip's standard incoming-webhook framework (see `zerver/webhooks/` for examples and the integrations framework docs in the repo). The new integration receives HTTP POSTs from the Redmine webhook plugin (the community `redmine_webhook` plugin format) and posts nicely formatted messages to a Zulip channel.

## Part 1: Remove the old plugin integration

- Remove the `"redmine"` entry from the `INTEGRATIONS` catalog in `zerver/lib/integrations.py` (it is currently registered as a plugin/legacy integration).
- Delete the old Redmine integration documentation template so the old plugin instructions no longer exist; the new webhook integration's documentation replaces it.

## Part 2: Add the `redmine` incoming webhook integration

Create a new incoming webhook integration named `redmine` (a `zerver/webhooks/redmine/` package with a view module and documentation, registered in the integrations catalog as a webhook integration), following the same conventions as existing webhook integrations such as those in `zerver/webhooks/`.

### Incoming payload format

The Redmine webhook plugin POSTs a JSON body with a single top-level `payload` object containing:

- `action`: a string; values include `"opened"` and `"updated"`.
- `url`: a string URL linking to the issue in Redmine.
- `issue`: an object with (at least):
  - `id`: integer issue number (e.g. `191`)
  - `subject`: string issue title (e.g. `"Found a bug"`)
  - `description`: string issue description
  - `author`: a user object with `firstname` and `lastname` string fields (plus other fields like `login`, `mail`, `id` that may be ignored)
  - `assignee`: either a user object of the same shape as `author`, or `null` when the issue is unassigned
  - other fields (`project`, `status`, `priority`, `tracker`, dates, etc.) that need not be rendered
- `journal` (present on update events): an object whose `notes` string field holds the comment/update text, along with its own `author` and metadata.

### Interface requirements

- A new incoming webhook integration named `redmine` is registered, reachable at the standard external-webhook URL `/api/v1/external/redmine` with the usual `api_key` and `stream` query parameters, following Zulip's existing incoming-webhook framework and view-naming convention.
- The webhook accepts the Redmine webhook-plugin JSON envelope described above: a top-level `payload` object containing `action`, `url`, `issue` (with `id`, `subject`, `description`, `author` with `firstname`/`lastname`, and `assignee` which is a user object or null), and, for updates, a `journal` object whose `notes` string holds the update comment.
- The Zulip topic for any issue event must be exactly `Issue #<id> <subject>` — for example, `Issue Found a bug`.
- For `action: "opened"`, the message body must be:

  ```
  **<author firstname> <author lastname>** opened [#<id> <subject>](<url>) for **<assignee firstname> <assignee lastname>**.
  ```

  When `assignee` is null, the ` for **...**` clause is omitted entirely, yielding:

  ```
  **<author firstname> <author lastname>** opened [#<id> <subject>](<url>).
  ```

  When a non-empty `description` exists, the sentence is followed by a blank line and then the description wrapped in a fenced quote block:

  ```
  ~~~ quote
  <description>
  ~~~
  ```

- For `action: "updated"`, the message body must be:

  ```
  **<author firstname> <author lastname>** updated [#<id> <subject>](<url>).
  ```

  followed, when non-empty `journal.notes` text exists, by a blank line and the notes wrapped in the same `~~~ quote` / `~~~` fenced block.
- Author and assignee display names are rendered as `<firstname> <lastname>`, joined by a single space.

### Worked example

Given a payload where `action` is `"opened"`, `url` is `https://example.com`, the issue has `id` 191, `subject` "Found a bug", `description` "I'm having a problem with this.", author `test user`, and assignee `test user`, the integration posts to topic `Issue Found a bug` with body:

```
**test user** opened [#191 Found a bug](https://example.com) for **test user**.

~~~ quote
I'm having a problem with this.
~~~
```

Given the same payload but with `assignee: null`, the first line is instead `**test user** opened [#191 Found a bug](https://example.com).` (same quoted description).

Given an `"updated"` payload for the same issue with `journal.notes` of "I've started working on this issue. The problem seems to be in the authentication module.", the body is:

```
**test user** updated [#191 Found a bug](https://example.com).

~~~ quote
I've started working on this issue. The problem seems to be in the authentication module.
~~~
```

### Additional expectations

- Include example payload fixture files for the integration (at minimum: an opened issue with an assignee, an opened issue with `assignee: null`, and an updated issue with journal notes) under the integration's fixtures directory, per the standard webhook-integration layout.
- Write user-facing documentation for the new integration explaining how to install and configure the Redmine webhook plugin to point at the Zulip webhook URL, following the standard incoming-webhook doc format.
- Update any catalog metadata (integration name, categories, logo reference) so the Redmine entry in the integrations catalog now refers to the webhook integration rather than the plugin one.
