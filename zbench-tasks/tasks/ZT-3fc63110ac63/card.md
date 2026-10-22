# ZT-3fc63110ac63 -- incoming-webhooks: Add OpenProject integration.

- lang: py   issue: #29944   tier: B
- fix: https://github.com/zulip/zulip/commit/3fc63110ac6360ad7d62b74464eef91823ac4629
- f2p: zerver.webhooks.openproject.tests.OpenProjectHookTests.test_attachment_created, zerver.webhooks.openproject.tests.OpenProjectHookTests.test_project_updated, zerver.webhooks.openproject.tests.OpenProjectHookTests.test_project_with_parent_created, zerver.webhooks.openproject.tests.OpenProjectHookTests.test_project_without_parent_created, zerver.webhooks.openproject.tests.OpenProjectHookTests.test_time_entry_with_invalid_iso, zerver.webhooks.openproject.tests.OpenProjectHookTests.test_time_entry_with_iso_hm, zerver.webhooks.openproject.tests.OpenProjectHookTests.test_time_entry_with_workpackage_created, zerver.webhooks.openproject.tests.OpenProjectHookTests.test_time_entry_without_workpackage_created, zerver.webhooks.openproject.tests.OpenProjectHookTests.test_work_package_created, zerver.webhooks.openproject.tests.OpenProjectHookTests.test_work_package_updated
- p2p: zerver.tests.test_integrations

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature (incoming webhook integration)",
  "reason": "Adding an OpenProject webhook integration is a real, commonly-assigned engineering task. The hidden grader is Zulip's standard webhook test pattern: it POSTs fixture payloads (the large JSON files are inputs, not assertions) and checks the resulting topic and short message strings \u2014 deterministic, observable outcomes of the handler's behavior, not brittle snapshots. Tests fail before the change (endpoint doesn't exist) and pass after, so it is cleanly gradable."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "A new incoming-webhook integration named `openproject` (display name \"OpenProject\") is added, following Zulip's standard webhook layout: module `zerver/webhooks/openproject/` reachable at the standard URL `/api/v1/external/openproject`, and registered in WEBHOOK_INTEGRATIONS so the endpoint is routed.",
    "The integration reads the event from the payload's `action` field (values of the form `<item>:<action>`) and supports exactly these events: `project:created`, `project:updated`, `work_package:created`, `work_package:updated`, `time_entry:created`, `attachment:created`; any other action value must be rejected as an unsupported webhook event type.",
    "Project events: message is `Project **{name}** was {action}.`; if a created project has a parent project (payload `project._embedded.parent.name`), the message is `Project **{name}** was created as a sub-project of **{parent}**.`; the topic is the project name.",
    "Work-package events: message is `**{subject}** (work package **{type}**) was {created|updated} by **{author}**.` using the work package's subject, its embedded type name, and embedded author name; the topic is the embedded project's name.",
    "Attachment created: message is `**{author}** uploaded **{fileName}** in **{container subject}**.` using the attachment's embedded author name, its `fileName`, and the subject of its embedded container work package; the topic is the container's project title (from the container's `project` link).",
    "Time-entry created: message is `**{user}** logged {duration}{location}.` where {user} is the embedded user's name; {duration} is the entry's ISO 8601 `hours` value rendered in bold as a human-readable list of days/hours/minutes/seconds with singular/plural unit names, comma-separated with `and` before the last unit (e.g. `**1 hour, 30 minutes**`); if the duration cannot be parsed the phrase `a time entry` is used instead; {location} is ` on **{workPackage subject}**` when the entry has an embedded work package, otherwise ` on **{project name}**`; the topic is the embedded project's name.",
    "The endpoint returns the standard Zulip webhook success response after sending the message."
  ],
  "reason": "This is a brand-new integration, so the test necessarily binds to new surface: the integration slug/URL, the set of supported event-type strings, and the exact topic and message wording per event. All of these are product-level contract that a Zulip integration ticket would legitimately pin (Zulip integration specs routinely dictate exact message templates and topics), and the fixture payloads are supplied by the test itself, not guessed by the solver. The view function name `api_openproject_webhook` and module path follow Zulip's pre-existing framework convention derived from the integration name, not an author-private choice. The test does not appear to reach internal helpers (e.g. `format_duration`), mock internals, or depend on private data structures; the duration-formatting and sub-project/fallback semantics are observable through message output and are enumerated above. With the listed requirements in the brief, the test grades behavioral correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The interface requirements plus the payload evidence pin down the endpoint, the exact six supported events, the exact message and topic formats (including the sub-project variant, the duration humanization rules with fallback, and the attachment container/project sourcing), and the unsupported-event handling, so two engineers working independently would produce compatible integrations."
}
