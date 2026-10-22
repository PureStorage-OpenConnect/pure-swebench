# Show a placeholder banner in the empty combined feed

## Background

In the Zulip web app, when a narrow (message view) contains no messages, a standard empty-narrow banner is rendered into the empty-feed notice area. The banner has a title line and, optionally, an HTML body line (often containing a link suggesting what the user could do next). This banner logic lives in the narrow-banner code path that decides, based on the current filter, which title/body to display (e.g., there are existing cases for empty search results, non-existent or private channels, etc.).

## Current behavior

When the user is viewing the **combined feed** (the view whose narrow filter is `in: home`) and it contains no messages at all, no placeholder banner is shown — the combined feed is currently treated as a case where the empty-narrow banner is suppressed, so the user just sees a blank feed.

## Required behavior

When the combined feed (`in: home`) is the current view and it has no messages, the standard empty-feed banner must be displayed, using the same structure and styling as the default empty-narrow placeholder:

- **Title:** `There are no messages in your combined feed.`
- **Body (HTML):** `Would you like to <a href="#narrow/channels/public">view messages in all public channels</a>?` — that is, the sentence "Would you like to view messages in all public channels?" where the phrase "view messages in all public channels" links to the hash URL `#narrow/channels/public` (the all-public-channels view).

Additional requirements:

- Both the title and the body must go through the standard translation machinery used by other empty-narrow banner strings (the title as a translated plain string, the body as translated HTML, consistent with how other banner bodies with links are produced).
- The body with the public-channels link is for regular (non-spectator) users. For spectators (logged-out visitors, where applicable), follow the existing conventions the banner code uses for spectator-facing empty states rather than showing this link if it is not appropriate for them.
- The banner must render into the same empty-feed notice container and use the same markup/styling as the existing default placeholder message; do not introduce a new visual treatment.
- Behavior for all other narrows (searches, single channels, DMs, etc.) must remain unchanged; only the combined-feed case gains a banner.

## Interface requirements

- When the user is in the combined feed view (narrow filter `in: home`) and it contains no messages, an empty-feed banner must be shown (previously the combined feed suppressed this banner) with the title "There are no messages in your combined feed."
- For non-spectator users, the banner body must be the HTML sentence `Would you like to <a href="#narrow/channels/public">view messages in all public channels</a>?` — i.e. the phrase "view messages in all public channels" is a link to the hash URL `#narrow/channels/public`; both title and body must go through the standard translation machinery.

## Acceptance criteria

1. Opening the combined feed when it has zero messages shows the placeholder banner with the exact title "There are no messages in your combined feed."
2. The banner body renders "Would you like to view messages in all public channels?" with "view messages in all public channels" hyperlinked to `#narrow/channels/public`.
3. The banner uses the existing empty-narrow banner template/styling and appears in the standard empty-feed notice area.
4. Both strings are translatable via the app's normal i18n mechanisms (plain translated string for the title, translated HTML for the body).
5. Empty-state banners for all other narrow types are unaffected.
