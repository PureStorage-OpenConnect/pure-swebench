# `sender:me` is not handled correctly when building search pills

## Context

Zulip's web client has a search box that converts typed search terms (like `sender:alice@example.com` or `channel:design`) into "pills". The search language supports a convenience alias: `sender:me` (and its negated form `-sender:me`), which should refer to the currently logged-in user.

The relevant code lives in the web frontend, primarily `web/src/filter.ts` (the `Filter` class, which parses narrow/search strings into term objects of the shape `{operator, operand, negated?}`) and the search-pill/validation logic that decides whether a typed term is a valid, pill-able search term.

## Current (buggy) behavior

If a user types `sender:me` into the search box and presses Enter without selecting a typeahead suggestion, the text is not converted into a search pill. The typeahead dropdown does show the correct suggestion for `sender:me`, but the direct-entry path fails: when the typed term is validated, the operand `me` is treated as a literal email address, and since no user is registered with the email `me`, the term is judged invalid and no pill is created.

## Required behavior

1. Typing `sender:me` (or `-sender:me`) in the search box and pressing Enter must produce a valid sender search pill referring to the current user, exactly as if the user had typed their own email address.
2. When parsing input for the purpose of creating search pills, the alias `me` used as the operand of the `sender` operator must be resolved to the current user's actual email address. Resolution must:
   - be case-insensitive on the operand (`me`, `Me`, `ME` all resolve),
   - work for both the plain and negated forms, preserving the negation flag on the resulting term (e.g. `-sender:me` yields `{operator: "sender", operand: "<current user's email>", negated: true}`),
   - leave all other operators and operands untouched.
3. Ordinary (non-pill) parsing of search/narrow strings must be completely unchanged: `sender:me` parsed outside the pill-creation flow must continue to behave exactly as it does today.
4. Validation of typed search terms must accept `me` as a valid operand for person-based operators such as `sender`, even though `me` is not a registered user's email. For example, given a realm where `ghost@zulip.com` is not a user, `sender:ghost@zulip.com` remains invalid, while `sender:me` is valid.

## Interface requirements

- `Filter.parse` gains an optional second boolean parameter, defaulting to `false`, that enables search-pill parsing mode. Callers pass it positionally as the second argument (e.g. `Filter.parse(input, true)` from the pill-creation code path). Omitting the argument must preserve the existing parsing behavior exactly.
- When that second parameter is `true` and a parsed term has operator `sender` with operand `me` (case-insensitive, with or without negation), `Filter.parse` resolves the operand to the current user's email address, producing a term like `{operator: "sender", operand: "<current user's email>"}` and preserving the `negated` flag when present.
- The existing search-term validation logic (`is_valid_search_term`) must accept the literal operand `me` as valid for person-based operators such as `sender`, even though `me` does not correspond to a registered user email.

## Acceptance sketch

- With a logged-in user whose email is `alice@example.com`: parsing `sender:me` in pill mode yields `[{operator: "sender", operand: "alice@example.com"}]`; parsing `-sender:me` in pill mode yields `[{operator: "sender", operand: "alice@example.com", negated: true}]`.
- Parsing `sender:leo+test@zulip.com` (any mode) still yields `[{operator: "sender", operand: "leo+test@zulip.com"}]`.
- Term validation: `sender:me` is valid; `sender:ghost@zulip.com` (unregistered email) is still invalid.
- In the UI, typing `sender:me` and pressing Enter (without picking a typeahead option) creates a sender pill for the current user.
