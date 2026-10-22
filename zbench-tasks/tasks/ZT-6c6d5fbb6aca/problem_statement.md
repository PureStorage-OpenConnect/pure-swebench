# Use locale-aware list formatting for user-facing name lists

## Background

Several places in the Zulip web client build user-facing strings by joining lists of items (most notably lists of user names) with `.join(", ")`. Hard-coding a comma separator produces awkward or incorrect output in many languages, since list punctuation and conjunctions vary by locale. User-facing lists should instead be rendered with the standard `Intl.ListFormat` API (using the user's current locale), which produces natural-language lists such as "A and B" or "A, B, and C" and translates correctly.

## Task

Sweep the web client (`web/src/`) for places where lists of items are joined with `.join(", ")` (or similar hard-coded separators) to produce user-facing text, and convert them to use locale-aware list formatting via `Intl.ListFormat`. Introduce a shared helper for this formatting (e.g. in the i18n module) rather than instantiating `Intl.ListFormat` ad hoc at every call site, so the locale is applied consistently.

Non-user-facing joins (e.g. building internal keys, query strings, or data attributes) must NOT be changed.

## Concrete required behavior changes

### `people.get_recipients`

Currently, `people.get_recipients(user_ids_string)` in `web/src/people` returns a single comma-joined string of recipient display names for a direct-message conversation. This bakes the ", " separator into a low-level data function, which prevents proper locale-aware rendering by callers.

Change it to return structured data instead of pre-joined text:

- It must return an **array** of recipient display names (strings), sorted alphabetically, rather than a comma-joined string.
- For a direct message with oneself (the only "other" participant is the current user), it must return a one-element array containing the current user's own full name. Example: for the current user alone, the result is `["Me Myself"]` (given that full name), not a joined string.
- For a conversation where the other participants are, e.g., a user named "Isaac Newton", the result is `["Isaac Newton"]`.
- Muted users must appear in the result as the translated "Muted user" placeholder name, each occupying its own array element. E.g. a conversation with Isaac Newton and one muted user yields `["Isaac Newton", <translated "Muted user">]`.
- All existing callers that previously used the returned string for display must be updated: they must format the array themselves — using the locale-aware list formatter when producing natural-language user-facing text, or another representation where appropriate.

### Group direct-message titles (`buddy_data.get_title_data`)

Currently, the title data computed by `buddy_data.get_title_data` for a group direct-message conversation (`is_group` true) has a first line that comma-joins the participant names, e.g. `"Human Selma, Old User"`.

Required behavior: the first line must render the participant names as a natural-language list with a conjunction, formatted for the user's locale. In English, two participants named "Human Selma" and "Old User" must render as `"Human Selma and Old User"` (not `"Human Selma, Old User"`). Three or more participants should render per the locale's conventions (e.g. "A, B, and C" in English). The second and third lines of the group title data are unchanged (empty strings).

### Other call sites

Apply the same conversion to other user-facing `.join(", ")` sites found in the sweep (e.g. compose/recipient labels, notification text, settings descriptions that enumerate names) so that all natural-language lists of items shown to the user go through the shared `Intl.ListFormat`-based helper.

## Interface requirements

- `people.get_recipients(user_ids_string)` must return an array of recipient display names sorted alphabetically, instead of a comma-joined string; any caller that needs a display string is responsible for joining/formatting the array itself.
- For a direct message with oneself, `people.get_recipients` must return a one-element array containing the current user's full name.
- Muted users must appear in the `people.get_recipients` result as the translated "Muted user" placeholder name, occupying their own array element.
- The group DM title (the first line of `buddy_data.get_title_data` for groups) must render recipient names as a natural-language list with a conjunction — e.g. two users render as "Human Selma and Old User" rather than "Human Selma, Old User".

## Notes

- The list formatting must respect the user's configured locale (the same locale used elsewhere for i18n), not a hard-coded English format.
- Preserve alphabetical sorting of names before formatting where that is the current behavior.
