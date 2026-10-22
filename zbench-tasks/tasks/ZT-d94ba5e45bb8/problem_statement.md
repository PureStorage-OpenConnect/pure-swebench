# Add support for GitLab deployment events to Zulip's GitLab webhook integration

## Background

Zulip's GitLab webhook integration (`zerver/webhooks/gitlab/`) handles many GitLab event types (push, merge request, pipeline, job, etc.), but it does not handle GitLab's *deployment events*. GitLab sends these when a deployment to an environment changes state; the webhook request carries the header `X-Gitlab-Event: Deployment Hook`, and the JSON payload has `"object_kind": "deployment"` plus a `status` field whose values include `running`, `success`, `failed`, and `canceled`.

Currently, when such a payload arrives at the GitLab webhook endpoint, the integration does not recognize the event and no message is sent to the configured channel.

## Required behavior

Extend the GitLab webhook integration so that deployment events produce Zulip messages, following the same structure used for the other GitLab event types in `gitlab/view.py` (and drawing on the shared message-formatting helpers in `zerver/lib/webhooks/git.py` where appropriate).

### Relevant payload fields

A GitLab deployment payload includes (among others):

- `status` — one of `running`, `success`, `failed`, `canceled`
- `environment` — e.g. `"production"`
- `deployable_url` — URL of the CI job performing the deployment, e.g. `https://gitlab.com/vedant8600317/test/-/jobs/9905389091`
- `commit_url` — URL of the deployed commit, e.g. `https://gitlab.com/vedant8600317/test/-/commit/58793660b22d6ceacbdc23b28a0562bca339702c`
- `commit_title` — e.g. `"Update .gitlab-ci.yml file"`
- `user` — object with `name` (e.g. `"Vedant Joshi"`), and a top-level `user_url` (e.g. `https://gitlab.com/theofficialvedantjoshi`)
- `project` — object with `name` (e.g. `"test"`), `web_url`, `path_with_namespace`, etc.
- `ref` — e.g. `"master"`

### Topic

Messages for deployment events go to the topic `<project name> / <environment>` — for the example payload above, `test / production`.

### Message content

- **status `running`** — announce that a new deployment started, attributing it to the user and quoting the deployed commit:

  `[Vedant Joshi](https://gitlab.com/theofficialvedantjoshi) started a new [deployment](https://gitlab.com/vedant8600317/test/-/jobs/9905389091):`
  `> [5879366](https://gitlab.com/vedant8600317/test/-/commit/58793660b22d6ceacbdc23b28a0562bca339702c) Update .gitlab-ci.yml file`

  The user's display name links to `user_url`; the word "deployment" links to `deployable_url`; the quoted line shows the commit's short SHA (first 7 characters) linking to `commit_url`, followed by the commit title. The short SHA is derived from the final path segment of `commit_url`.

- **status `success`** — `The [deployment](https://gitlab.com/vedant8600317/test/-/jobs/9905389091) was successful.`
- **status `failed`** — `The [deployment](https://gitlab.com/vedant8600317/test/-/jobs/9905389091) failed.`
- **status `canceled`** — `The [deployment](https://gitlab.com/vedant8600317/test/-/jobs/9905389091) was canceled.`

In every case the word "deployment" is a markdown link to `deployable_url`; if that URL is missing from the payload, render the plain word "deployment" without a link.

### Other requirements

- The event must be recognized via the `X-Gitlab-Event: Deployment Hook` header, integrating with the existing event-dispatch mechanism in `gitlab/view.py` (which also honors the integration's event-filtering query parameter, so `Deployment Hook` should be filterable like other event types).
- Add representative sample payloads under `zerver/webhooks/gitlab/fixtures/`, one per status, following the existing naming convention that maps a fixture file to its `X-Gitlab-Event` header (i.e. `deployment_hook__running.json`, `deployment_hook__success.json`, `deployment_hook__failed.json`, `deployment_hook__canceled.json`).
- Behavior for all other GitLab event types must be unchanged.

## Interface requirements

- Support the GitLab 'Deployment Hook' webhook event (the value GitLab itself sends in the X-Gitlab-Event header for deployment events; test fixtures named deployment_hook__<status>.json map to this header via the existing fixture-to-header convention).
- Topic name for deployment events: '<project name> / <environment>' (e.g. 'test / production'), taking the project name from payload.project.name and the environment from payload.environment.
- Message for status 'running': '[<user name>](<user_url>) started a new [deployment](<deployable_url>):\n> [<short sha>](<commit_url>) <commit_title>' — user name/URL from payload.user.name and payload.user_url, deployment link from payload.deployable_url, quoted line links the commit.
- Short sha in the running message: first 7 characters of the commit SHA (derived from the commit URL's final path segment), e.g. '5879366'.
- Message for status 'success': 'The [deployment](<deployable_url>) was successful.'
- Message for status 'failed': 'The [deployment](<deployable_url>) failed.'
- Message for status 'canceled': 'The [deployment](<deployable_url>) was canceled.'
- The word 'deployment' is rendered as a markdown link to payload.deployable_url in all four messages (plain text 'deployment' if the URL is absent).
