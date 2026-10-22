# Make web-public channel content discoverable by AI agents via llms.txt

## Background

Zulip organizations can enable "spectator access" (the realm setting `enable_spectator_access`), which lets logged-out visitors read channels marked web-public through the web UI. There is also an existing unauthenticated JSON API for reading web-public content: `GET /json/messages` can be fetched without logging in, provided the request's `narrow` includes the `channels` operator with operand `web-public`.

In practice, however, AI assistants and other automated agents that are handed a link to a Zulip conversation cannot figure out how to read it. Nothing on the server advertises that an unauthenticated API exists, which channels are web-public, or how to construct a valid request. The goal of this task is to make that information machine-discoverable using the llms.txt convention (https://llmstxt.org/): a plain-text markdown document served at `/llms.txt` at the site root, plus a hint in the homepage HTML that points agents at it.

## Required behavior

### 1. New endpoint: `GET /llms.txt`

Add a server endpoint at `/llms.txt` (no authentication required) with the following behavior:

- **When the realm has spectator access enabled AND has at least one web-public channel:** respond `200` with `Content-Type: text/plain`. The body is a markdown document per the llms.txt convention and must begin with a `#` heading on the first line.
- **When the realm has spectator access disabled:** respond `404`.
- **When spectator access is enabled but the realm has zero web-public channels:** respond `404`.

The body of the document must:

- Explain how to fetch messages without authentication using the existing `GET /json/messages` API, explicitly stating that the `narrow` parameter must include the `channels` operator with operand `web-public`. The literal strings `/json/messages`, `channels`, and `web-public` must appear in the document.
- List the realm's web-public channels by name. Channels that are not web-public — both private channels and ordinary (members-only-visible) public channels — must not appear anywhere in the document.

### 2. Homepage hint for AI agents

The homepage HTML (`/`) must include a comment addressed to AI agents. This applies to **both** the logged-in app page and the spectator (logged-out) view of a web-public-enabled realm. The comment must contain the literal phrase `AI assistant:` in the rendered HTML.

The comment's content depends on the realm's web-public status:

- **When the realm has web-public streams enabled (spectator access on):** the comment must reference `/llms.txt`, directing agents there for instructions.
- **When web-public access is not enabled:** the page must not mention `/llms.txt` anywhere, and the comment must instead inform agents that the organization has no web-public content — the exact phrase `does not have web-public channels` must appear in the HTML.

Both variants render in the served HTML (an HTML comment is fine — the requirement is on the raw HTML content, not visible text).

## Interface requirements

- The server gains a new endpoint `GET /llms.txt` (per the llms.txt convention, https://llmstxt.org/) that responds `200` with `Content-Type: text/plain` and a body that begins with a markdown `#` heading.
- `GET /llms.txt` must return `404` when the realm does not have web-public stream access enabled (spectator access disabled).
- `GET /llms.txt` must return `404` when web-public access is enabled but the realm has zero web-public channels.
- The `/llms.txt` body must document how to fetch messages without authentication via the existing `GET /json/messages` API, explicitly mentioning that the narrow must include the `channels` operator with operand `web-public`.
- The `/llms.txt` body must list the realm's web-public channels by name, and must not list channels that are not web-public (private or ordinary public channels are excluded).
- The homepage HTML (both the logged-in app and the spectator/logged-out view) must include a comment addressed to AI agents containing the literal phrase `AI assistant:`.
- When the realm has web-public streams enabled, that homepage comment must reference `/llms.txt`; when web-public streams are not enabled, the page must not mention `/llms.txt` and the comment must instead state that the organization `does not have web-public channels` (that exact phrase appears in the HTML).

## Notes

- Zulip is multi-tenant: "the realm" means the realm resolved from the request's subdomain, so the endpoint and homepage comment must reflect that specific realm's settings and channels.
- The realm setting governing web-public access is `enable_spectator_access`; a channel is web-public when its `is_web_public` flag is set.
- No new authentication or message-serving logic is needed — `/llms.txt` only documents and advertises the existing unauthenticated read path.
