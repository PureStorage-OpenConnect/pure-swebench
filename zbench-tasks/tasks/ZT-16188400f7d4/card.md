# ZT-16188400f7d4 -- password: Add password limit inidcator to form.

- lang: web   issue: #27922   tier: B
- fix: https://github.com/zulip/zulip/commit/16188400f7d41a30d82d1867f911fb6cd160b40d
- f2p: web/tests/password.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, assignable engineering task: enforce a maximum password length in the client-side password quality check and surface an error message, driven by a labeled bug report. The hidden test grades observable behavior deterministically \u2014 password_quality returns false for an over-length password, the danger class is applied, and password_warning returns the max-length message. The single string equality is a short, user-facing error message (the very behavior the fix adds), not a long snapshot or incidental formatting, and it sits alongside behavioral assertions, so it fails before the fix and passes after without brittleness concerns."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The change-password input element gains a new HTML data attribute `data-max-length`, populated with the realm's maximum allowed password length (alongside the existing `data-min-length` and `data-min-guesses` attributes).",
    "`password_quality(password, $bar, $password_field)` (existing public function) must read the maximum length from the field's `data-max-length` attribute and return false for any password longer than that limit, styling the strength bar with the existing `bar-danger` class in that case.",
    "`password_warning(password, $password_field)` (existing public function) must, for a password exceeding the field's `data-max-length`, return the user-facing message: 'Maximum password length: {max} characters.' \u2014 exact wording, with the configured limit interpolated and a trailing period, passed through the standard translation mechanism."
  ],
  "reason": "The test exercises only the pre-existing public functions `password_quality` and `password_warning` and the pre-existing `bar-danger` failure styling. The only new names it binds to are (a) the `data-max-length` DOM attribute on the password field and (b) the exact user-facing warning string. Both are legitimate spec surface: the attribute is the declared carrier of a new setting on a UI element (mirroring the existing `data-min-length`/`data-min-guesses` convention), and tickets routinely pin user-visible message wording. The test's fake password field is just a stand-in for the real DOM element's attribute contract, not a mock of internal helpers, and the 1e20 min-guesses value is merely a way to isolate the length check, not a contract item. Handed the three contract items above, a solver would be graded on correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue precisely identifies the three server-side surfaces (RegistrationForm, LoggingSetPasswordForm, the password-change endpoint) and the registration.html maxlength attribute, and the expected-behavior evidence plus interface requirements pin down the client-side contract exactly: data-max-length attribute, password_quality returning false with bar-danger for over-long passwords, and the exact translated warning string 'Maximum password length: {max} characters.' Two engineers working from this brief would produce compatible implementations."
}
