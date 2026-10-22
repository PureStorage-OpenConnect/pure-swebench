# ZT-b9c037e0ee3d -- realm_playground: Use Intl.ListFormat rather than .join(",").

- lang: web   issue: #26936   tier: B
- fix: https://github.com/zulip/zulip/commit/b9c037e0ee3da7be83a6d22d34dc86db0ab3fe52
- f2p: web/tests/realm_playground.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior-affecting refactor (i18n formatting fix)",
  "reason": "This is a real, assignable engineering change: replacing .join(', ') with locale-aware list formatting changes the observable output of get_pygments_typeahead_list_for_settings. It is not translation-string churn \u2014 it's a code behavior change. The hidden test exercises the function directly and checks short, deterministic label strings under a fixed test locale, not a large snapshot or incidental formatting, so it fails before and passes after the change deterministically."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test exercises the pre-existing public function get_pygments_typeahead_list_for_settings and checks its user-visible output (the language label strings). The only addition is a call to initialize_user_settings, a module and function that already exist at the base commit; it merely sets up standard client state (the fix's locale-aware list formatting reads user settings, and initializing them is harmless for any alternative implementation). The test does not reference the new internal helper util.format_array_as_list_with_conjuction, its 'narrow' style argument, or any other name invented by the fix, so a solver is graded on the rendered label behavior, not on guessing the author's internal choices."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the goal (replace .join(\", \") with Intl.ListFormat for user-facing lists), and the evidence pinpoints a concrete, checkable conversion site: realm_playground's settings typeahead now depends on user settings (locale source) and must work when settings are minimally initialized. Together these determine an observable outcome: a locale-aware list formatter driven by user_settings.default_language with graceful fallback, applied at least to the playground alias list, with English output remaining a comma-separated enumeration."
}
