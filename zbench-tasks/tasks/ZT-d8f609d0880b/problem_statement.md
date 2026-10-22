# Make unresolved topics easier to search for

## Background

Zulip's web client lets users filter messages with search operators like `is:resolved`, which narrows to topics that have been marked as resolved. Any operator can be negated with a leading dash (e.g. `-is:resolved` means "not resolved"). The search bar has two related pieces of user-facing text:

1. **Narrow descriptions** — a human-readable description of the current filter, produced by `Filter.search_description_as_html` in the web frontend (used, e.g., for the search box placeholder/description of the active narrow).
2. **Typeahead suggestions** — as the user types in the search bar (or focuses it with an empty query), a list of suggested search terms is shown, each with a search string (e.g. `is:resolved`) and a short description line.

### Current behavior

- `is:resolved` is described as "topics marked as resolved".
- Negated terms are described by prefixing "exclude " to the positive description, so `-is:resolved` reads as "Exclude topics marked as resolved" in suggestion lines.
- The typeahead suggests `is:resolved`, but there is no dedicated suggestion for finding *unresolved* topics; a user has to know to type `-is:resolved` themselves.

## Required behavior

Make searching for unresolved topics a first-class experience:

1. **Wording of the resolved description.** The narrow description for `is:resolved` must read exactly `resolved topics` (replacing "topics marked as resolved").
2. **Natural negative wording.** When an operand has a natural English negative word, a negated term should use that word instead of the generic "exclude " prefix. Currently this applies to `resolved`: a filter term `{operator: "is", operand: "resolved", negated: true}` must be described as exactly `unresolved topics` by `Filter.search_description_as_html`.
3. **Typeahead suggestion for unresolved topics.** The search typeahead must offer a suggestion whose search string is `-is:resolved` and whose description line reads `Unresolved topics` (sentence-case capitalization as rendered in the suggestion line), replacing the generic "Exclude topics marked as resolved" wording. This suggestion should surface for user intents like typing "unresolved", so it inserts a `-is:resolved` pill when selected.
4. **Empty-query suggestions.** When the search box is focused with an empty query, the suggestion list must include `-is:resolved`, placed immediately after the `is:resolved` suggestion and before the sender/channel suggestions.
5. **No change to other negated suggestions.** Other negated `is:` operands keep the default "Exclude ..." phrasing — e.g. `-is:followed` must still be described as `Exclude followed topics`, `-is:starred` as `Exclude starred messages`, etc. Only operands with a natural negative word (currently only `resolved`) get the special wording. Invalid operands (e.g. `is:something_we_do_not_support`) keep their existing error description.

## Interface requirements

- The search-bar narrow description for `is:resolved`, as returned by the existing `Filter.search_description_as_html`, must read exactly `resolved topics` (changed from "topics marked as resolved").
- A negated `is:resolved` term (`{operator: "is", operand: "resolved", negated: true}`) must be described as exactly `unresolved topics` — using the natural negative word instead of the default "exclude " prefix.
- The search typeahead must offer a suggestion with search string `-is:resolved` whose description reads `Unresolved topics` (rendered with sentence-case capitalization in the suggestion line), replacing the generic "Exclude topics marked as resolved" wording.
- The suggestion list for an empty search query must include `-is:resolved`, placed immediately after the `is:resolved` suggestion and before the sender/channel suggestions.
- Other negated `is:` suggestions keep the default "Exclude ..." phrasing (e.g. `-is:followed` → `Exclude followed topics`); only operands with a natural negative word (currently "resolved") get special wording.

## Implementation notes

- The relevant code lives in the web frontend: the filter/description logic (`web/src/filter.ts`) and the search suggestion generation (`web/src/search_suggestion.ts`). Design the negative-word handling as data (a mapping from operand to its natural negative phrase) rather than a one-off conditional, so future operands can be added easily.
- User-facing strings should go through the codebase's usual translation/marking conventions for UI text.
