# Enforce and surface the maximum password length instead of silently truncating

## Background

Zulip enforces a maximum password length on the server via `RegistrationForm.MAX_PASSWORD_LENGTH` (currently `100`). However, the enforcement today is inconsistent and invisible to users:

- **Registration form (`RegistrationForm`)**: a password longer than the limit is silently accepted and truncated to the maximum length, rather than rejected. Additionally, the password input in `registration.html` carries a sneaky `maxlength="{{ MAX_PASSWORD_LENGTH }}"` HTML attribute, so the browser itself silently truncates typed input before it is ever submitted.
- **Password reset form (`LoggingSetPasswordForm`)**: same silent-truncation behavior.
- **Password change flow** (the `accounts/password/reset/` endpoint used from *Personal settings > Account & Privacy* to change one's password): does not enforce `MAX_PASSWORD_LENGTH` at all, so it is inconsistent with the other forms.

Silently truncating a password is a bad experience: the user believes their full password was set, and later login attempts with the full password fail.

## Required behavior

### Server side

1. In `RegistrationForm`, a submitted password longer than `MAX_PASSWORD_LENGTH` must be rejected with a validation error carrying a clear, user-facing message stating the maximum allowed length — not truncated. This can be done the same way weak passwords are already rejected there (the `not check_password_strength(password)` path raises a `ValidationError` with a message).
2. `LoggingSetPasswordForm` must apply the same maximum-length validation with the same style of user-facing error.
3. The password change flow used from Personal settings (the `accounts/password/reset/` endpoint) must enforce the same `MAX_PASSWORD_LENGTH` limit, so all three places that set a password behave consistently.
4. Remove the `maxlength` attribute from the password input in `registration.html` so the browser no longer silently truncates input; the user should be able to type an over-long password and then see the error message.

### Client side (live password-quality feedback)

The web client already gives live feedback on password quality via the `password_quality` module, driven by data attributes on the password input (`data-min-length`, `data-min-guesses`). This feedback must now also account for the maximum length; see "Interface requirements" below.

Concretely, if the configured maximum is 20 and the user has typed a 30-character password (even a very strong one), the quality indicator must show it as unacceptable: the strength bar gets the `bar-danger` styling, `password_quality` reports the password as not accepted, and the warning text shown to the user is `Maximum password length: 20 characters.`

Passwords at or under the maximum are unaffected: existing minimum-length and strength (min-guesses) behavior, bar percentages, and styling must not change.

## Interface requirements

- The change-password input element gains a new HTML data attribute `data-max-length`, populated with the realm's maximum allowed password length (alongside the existing `data-min-length` and `data-min-guesses` attributes).
- `password_quality(password, $bar, $password_field)` (existing public function) must read the maximum length from the field's `data-max-length` attribute and return `false` for any password longer than that limit, styling the strength bar with the existing `bar-danger` class in that case.
- `password_warning(password, $password_field)` (existing public function) must, for a password exceeding the field's `data-max-length`, return the user-facing message `Maximum password length: {max} characters.` — exact wording, with the configured limit interpolated in place of `{max}` and a trailing period — passed through the standard translation mechanism (i.e., a translatable string, like the existing "Password should be at least N characters long" message).

## Acceptance summary

- Submitting an over-long password during registration or password reset produces a visible validation error naming the limit; nothing is truncated.
- Changing one's password from Personal settings enforces the same limit.
- The registration page's password input no longer has a browser-side `maxlength` cap.
- The live password-strength UI marks over-long passwords as unacceptable (`bar-danger`, not accepted) and shows the exact translated message above, driven by the input's `data-max-length` attribute.
