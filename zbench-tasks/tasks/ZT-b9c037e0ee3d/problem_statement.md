# Use locale-aware list formatting (`Intl.ListFormat`) instead of `.join(", ")` for user-facing lists

## Problem

In the Zulip web frontend (`web/src/`), several places build user-facing strings by joining an array with a hard-coded separator, e.g. `items.join(", ")`. A hard-coded `", "` is only correct for some languages; many locales use different list separators and conventions. JavaScript's built-in `Intl.ListFormat` produces correctly localized list strings, so user-visible lists should be formatted with it instead.

## Required behavior

1. **Shared list-formatting helper.** Add a reusable utility function in the web frontend (a natural home is `web/src/util.ts`) that takes an array of strings and returns a single human-readable list string produced via `Intl.ListFormat`.
   - The locale passed to `Intl.ListFormat` must be the user's configured Zulip language (the `default_language` value from the user's settings, i.e. the `user_settings` module), not a hard-coded locale.
   - If the user's language setting is not set/available (e.g. the settings object is present but empty), the helper must fall back gracefully to the environment's default locale rather than throwing.
   - The locale must be read at **call time**, each time a list is formatted — not captured once at module import time — so that code paths which run after user settings are initialized pick up the correct language.
   - The helper should let callers choose the `Intl.ListFormat` style/type appropriate to the string (e.g. a prose-style conjunction list like "a, b, and c" vs. a plain enumeration like "a, b, c").

2. **Sweep and convert user-facing join sites.** Search the web frontend for `.join(", ")` (and equivalent hard-coded-separator joins) that produce text shown to users, and convert them to the new helper. One site that must be converted:
   - `web/src/realm_playground.ts`: `get_pygments_typeahead_list_for_settings` builds typeahead labels for the code-playground language picker of the form `Language (alias1, alias2, ...)`. The alias enumeration inside the parentheses must be produced by the locale-aware helper instead of `.join(", ")`. Because this function now depends on user settings for the locale, it must still work correctly (no crash, sensible default-locale output) when user settings contain no language preference.

3. **Behavior in English.** For an English locale, plain enumerations should still read as a comma-separated list (e.g. aliases render as `py, python3`), so existing English-language UI text remains natural; prose-style lists may render with a conjunction (e.g. "a, b, and c") where that reads better.

4. **Out of scope.** Joins that are not user-facing — log output, generated code/markup syntax, URLs, CSS selectors, test fixtures, etc. — must be left unchanged.

## Interface requirements

No specific exported names are mandated beyond the behaviors above; keep `get_pygments_typeahead_list_for_settings` in `web/src/realm_playground.ts` with its existing signature and label format, changing only how the alias list portion is joined.
