# ZT-4adb853ef929 -- i18n: Write language name in the language itself.

- lang: web   issue: #14565   tier: B
- fix: https://github.com/zulip/zulip/commit/4adb853ef92932ac70c18e2de06da884ef6084f1
- f2p: web/tests/i18n.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature (i18n UX: display language names in their own language)",
  "reason": "Real, assignable engineering task with an observable behavior change: settings language picker names switch from English names to native names via Intl.DisplayNames, with hard-coded exceptions for 'bqi' and 'mn'. The hidden test grades exactly that observable outcome \u2014 short per-language display strings like '\u041c\u043e\u043d\u0433\u043e\u043b (53%)' and '\u4e2d\u6587 (\u7b80\u4f53) (86%)' \u2014 which are the behavior itself, not incidental formatting or a bulk snapshot. Output is deterministic under the benchmark's pinned Node/ICU runtime (Intl.DisplayNames results only vary across ICU versions, not across runs). The test also fails-before/passes-after (e.g. 'English' \u2192 'English (United States)', 'Bahasa Indonesia (32%)' \u2192 'Indonesia (32%)'), so it meets the verifiability bar. None of the drop conditions apply: this is not rename/docs/i18n-string churn (it changes rendering logic, not translation catalogs), not version/time-gated, and the assertions are targeted field-level checks rather than a whole rendered snapshot."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The language-picker list (output of the existing get_language_list_columns) must show each language's name in that language itself (its autonym), computed from the language code via Intl.DisplayNames, instead of the server-provided English name; the first character is uppercased according to the locale (e.g. 'id' \u2192 'Indonesia', 'mn' \u2192 '\u041c\u043e\u043d\u0433\u043e\u043b').",
    "If the language code contains a script subtag, the script's localized display name is appended in parentheses (e.g. 'zh-hans' \u2192 '\u4e2d\u6587 (\u7b80\u4f53)').",
    "If the language code contains a region subtag, the region's localized display name is appended in parentheses (e.g. 'en-gb' \u2192 'English (United Kingdom)').",
    "The code 'en' must be displayed as US English, i.e. rendered as 'English (United States)'.",
    "The languages 'bqi' and 'mn' must display the fixed names 'Bakhtiari' and '\u041c\u043e\u043d\u0433\u043e\u043b' respectively, because Intl.DisplayNames returns English names for them in some browsers.",
    "The existing translation-percentage suffix format is preserved: the display name is followed by ' (NN%)' when percent_translated is defined, and omitted for the fully translated default language."
  ],
  "reason": "The test only exercises pre-existing public entry points (initialize, get_language_name, get_language_list_columns) and asserts user-visible strings in the existing name_with_percent field \u2014 it never touches the new display_name field, the private get_language_display_name helper, or any mocks of internals. However, the exact expected strings encode product decisions a solver could not guess from the code alone: mapping 'en' to 'en-US', appending script and region in parentheses, locale-aware capitalization, and hard-coded autonyms for 'bqi' and 'mn'. These are exactly the kind of user-facing wording/formatting rules a ticket would legitimately pin, so with the contract above the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the goal (all language names shown as autonyms), and the evidence plus interface requirements pin down a determinate, checkable mechanism: compute autonyms client-side via Intl.DisplayNames in get_language_list_columns, with locale-aware first-letter uppercasing, script/region subtag handling in parentheses, en \u2192 English (United States), fixed overrides for bqi and mn, and unchanged percentage-suffix formatting. Concrete input/output examples make independent implementations compatible."
}
