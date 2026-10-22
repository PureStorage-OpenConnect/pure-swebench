# Fix misleading credential placeholders in generated curl API documentation examples

## Background

Zulip's API documentation includes auto-generated `curl` code examples for each REST endpoint. These examples currently show HTTP Basic Auth credentials using the placeholder `-u BOT_EMAIL_ADDRESS:BOT_API_KEY`.

This wording is confusing and misleading for two reasons:

1. The Zulip API can be used by any user account, not just bots, so prefixing the placeholders with `BOT_` wrongly suggests the examples only apply to bot accounts.
2. Readers have reported the naming is confusing because it's not obvious what value to substitute or where to obtain it.

Additionally, the generated examples give the reader no guidance on how to actually obtain valid credentials (their email and API key) to substitute for the placeholders.

## Required behavior

### 1. Rename the credential placeholders

In all generated curl examples that authenticate, the Basic Auth line must read:

```
    -u EMAIL_ADDRESS:API_KEY \
```

i.e. the email placeholder is `EMAIL_ADDRESS` and the API key placeholder is `API_KEY`, with no `BOT_` prefix. This applies everywhere curl examples are generated or rendered, including the curl-example generation pipeline for the OpenAPI-based API docs and the Markdown extension that renders `curl` code blocks. Any documentation pages, fixtures, or supporting text that reference the old `BOT_EMAIL_ADDRESS` / `BOT_API_KEY` placeholders should be updated for consistency.

For example, a generated example for `GET /get_stream_id` should render its curl block as:

```
curl -sSX GET -G http://localhost:9991/api/v1/get_stream_id \
    -u EMAIL_ADDRESS:API_KEY \
    --data-urlencode stream=Denmark
```

The Markdown processing for `curl` code blocks (including its error/edge-case handling paths) must accept and pass through the new `EMAIL_ADDRESS:API_KEY` form exactly as it previously handled `BOT_EMAIL_ADDRESS:BOT_API_KEY`.

### 2. Add shared "how to get your credentials" instructions above each authenticated example

Create a shared documentation snippet named `curl-auth-credentials.md` (in the directory where the API docs' Markdown include files live) containing brief instructions explaining that `EMAIL_ADDRESS` and `API_KEY` in the example should be replaced with the reader's own email address and API key, and how/where to obtain the API key.

Every generated curl example for an endpoint that requires authentication must begin with the Markdown include directive for this snippet, followed by a blank line, immediately before the opening code fence. Concretely, the generated Markdown must start with the literal prefix:

```
{!curl-auth-credentials.md!}

```

followed directly by the ```` ```curl ```` fence. So the full generated output for an authenticated endpoint looks like:

```
{!curl-auth-credentials.md!}

```curl
curl -sSX GET -G http://localhost:9991/api/v1/get_stream_id \
    -u EMAIL_ADDRESS:API_KEY \
    --data-urlencode stream=Denmark
```
```

This prefix must be present regardless of how the example is generated (with or without parameter examples in the OpenAPI spec, with path parameters, with JSON object parameters, with a custom `api_url`, with excluded/included parameter lists, etc.).

### 3. Exempt the unauthenticated credential-fetching endpoints

The two endpoints used to obtain an API key in the first place do not themselves require authentication and must NOT get the credentials-instructions prefix:

- `POST /dev_fetch_api_key`
- `POST /fetch_api_key`

Generated curl examples for these endpoints must begin directly with the ```` ```curl ```` fence, with no `{!curl-auth-credentials.md!}` include and no `-u` credentials line (they authenticate via their own request parameters, not Basic Auth).

## Interface requirements

- The authentication placeholder in generated curl documentation examples changes from `BOT_EMAIL_ADDRESS:BOT_API_KEY` to `EMAIL_ADDRESS:API_KEY` (email placeholder `EMAIL_ADDRESS`, API key placeholder `API_KEY`), since these examples apply to any user, not just bots.
- Every generated curl example for an endpoint requiring authentication must begin with the markdown include directive `{!curl-auth-credentials.md!}` followed by a blank line (i.e. the literal prefix `{!curl-auth-credentials.md!}\n\n`) immediately before the ```` ```curl ```` code fence, pulling in shared instructions on obtaining credentials.
- The unauthenticated API-key-fetch endpoints (`POST /dev_fetch_api_key` and `POST /fetch_api_key`) must NOT receive the `{!curl-auth-credentials.md!}` prefix; their examples still begin directly with the ```` ```curl ```` fence.

## Acceptance criteria

- No generated curl example anywhere in the API docs shows `BOT_EMAIL_ADDRESS` or `BOT_API_KEY`.
- Authenticated endpoints' generated examples carry the exact `{!curl-auth-credentials.md!}\n\n` prefix before the ```` ```curl ```` fence; the two API-key-fetch endpoints do not.
- The `curl-auth-credentials.md` include file exists and resolves when API docs pages are rendered, so docs pages build without missing-include errors.
- The curl code-block Markdown extension renders examples using the new placeholders correctly, including its error-handling paths (e.g. when an example uses an unsupported option and falls back to rendering the raw block).
