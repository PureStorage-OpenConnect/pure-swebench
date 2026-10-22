# Add an OpenProject incoming-webhook integration to Zulip

## Background

OpenProject is an open-source project management system that can send outgoing webhooks (JSON POST requests) when things happen in a project: projects are created or updated, work packages (tasks/issues) are created or updated, time entries are logged, and attachments are uploaded. Zulip currently has no integration for OpenProject. Build one following Zulip's standard incoming-webhook integration pattern (as used by the existing integrations under `zerver/webhooks/`), including documentation and a logo so it appears in the integrations catalog.

## OpenProject payload shape

Every OpenProject webhook payload is a JSON object with an `action` field of the form `"<item>:<action>"` (e.g. `"work_package:created"`, `"time_entry:created"`), plus a top-level object keyed by the item type (e.g. `project`, `work_package`, `time_entry`, `attachment`) containing the item in OpenProject's HAL/JSON API v3 format. Related resources are nested under the item's `_embedded` key (e.g. `work_package._embedded.author.name`, `work_package._embedded.project.name`, `work_package._embedded.type.name`, `time_entry._embedded.user.name`, `attachment._embedded.author`, `attachment._embedded.container` — the container is the work package the attachment belongs to). Link-style references live under `_links` (e.g. the attachment container's project is available as `container._links.project.title`). Time entries carry their duration in an ISO 8601 duration string in the `hours` field (e.g. `"PT1H30M"`).

## Required behavior

### Supported events and messages

The integration must support exactly these six `action` values and produce the following Zulip messages (Markdown, `**bold**` as shown):

1. **`project:created`** — message: `Project **{name}** was created.` where `{name}` is `project.name`. Exception: if the created project has a parent project (present at `project._embedded.parent.name`), the message is instead `Project **{name}** was created as a sub-project of **{parent}**.` Topic: the project's name.

2. **`project:updated`** — message: `Project **{name}** was updated.` Topic: the project's name. (No parent-project variant for updates.)

3. **`work_package:created`** — message: `**{subject}** (work package **{type}**) was created by **{author}**.` where `{subject}` is `work_package.subject`, `{type}` is the embedded type's name (e.g. `Task`), and `{author}` is the embedded author's name. Topic: the embedded project's name.

4. **`work_package:updated`** — same format with `updated`: `**{subject}** (work package **{type}**) was updated by **{author}**.` Topic: the embedded project's name.

5. **`time_entry:created`** — message: `**{user}** logged {duration}{location}.` where:
   - `{user}` is the embedded user's name.
   - `{duration}` is the entry's ISO 8601 `hours` value rendered in bold as a human-readable list of time units in descending order — days, hours, minutes, seconds — including only non-zero units, with singular/plural unit names (`1 hour` vs `2 hours`), comma-separated with `and` before the final unit. Examples: `PT1H30M` → `**1 hour, 30 minutes**`; `PT1H` → `**1 hour**`; `P1DT2H3M4S` → `**1 day, 2 hours, 3 minutes and 4 seconds**`.
   - If the `hours` value cannot be parsed as an ISO 8601 duration, use the literal phrase `a time entry` in place of the bolded duration.
   - `{location}` is ` on **{workPackage subject}**` when the time entry has an embedded work package; otherwise it falls back to ` on **{project name}**` using the embedded project.
   - Topic: the embedded project's name.

6. **`attachment:created`** — message: `**{author}** uploaded **{fileName}** in **{container subject}**.` where `{author}` is the attachment's embedded author name, `{fileName}` is `attachment.fileName`, and `{container subject}` is the `subject` of the attachment's embedded container work package. Topic: the container's project title, taken from the container's `project` entry under `_links` (its `title`).

Any other `action` value must be rejected as an unsupported webhook event type, using Zulip's standard mechanism for unsupported webhook events (so it is reported/logged the same way other integrations handle unknown event types, rather than silently ignored or crashing).

### Success response

After sending the message, the endpoint must return Zulip's standard webhook success response.

## Interface requirements

- A new incoming-webhook integration named `openproject` (display name "OpenProject") following Zulip's standard webhook layout: a module at `zerver/webhooks/openproject/` reachable at the standard URL `/api/v1/external/openproject`, and registered in `WEBHOOK_INTEGRATIONS` so the endpoint is routed and the integration appears in the catalog.
- The integration reads the event from the payload's `action` field (values of the form `<item>:<action>`) and supports exactly these events: `project:created`, `project:updated`, `work_package:created`, `work_package:updated`, `time_entry:created`, `attachment:created`; any other action value must be rejected as an unsupported webhook event type.
- Message and topic formats exactly as specified in "Required behavior" above.

## Additional expectations

- Follow the conventions of existing Zulip webhook integrations: a `view.py` with a `@webhook_view`-decorated endpoint, typed payload access (e.g. via Zulip's payload wrapper utilities), an `__init__.py`, a `doc.md` documentation page describing how to configure the webhook in OpenProject, and registration so the integration shows up in the integrations directory.
- Topics and message content must be built from the payload only; the integration takes no special URL parameters beyond the standard ones (api key, stream, topic overrides) that all Zulip webhooks support, and standard user-specified topic overrides should behave as they do for other integrations.
