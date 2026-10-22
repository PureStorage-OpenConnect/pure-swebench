# ZT-c44c153b9af8 -- settings: Improve UI for email changes.

- lang: web   issue: #31975   tier: B
- fix: https://github.com/zulip/zulip/commit/c44c153b9af87f6b0b5638dfa91bd6c5e014a6d3
- f2p: web/tests/settings_org.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "ui-improvement/feature",
  "reason": "Real, assignable settings-UI change with observable behavior: when email changes are disabled, the change-email button is now hidden (class 'hide') instead of disabled, alongside a restructured email field. The hidden test in settings_org.test.cjs deterministically toggles realm_email_changes_disabled and asserts the button's hide class and label cursor state \u2014 it fails before the change (which set the disabled prop) and passes after. Assertions are targeted boolean class/state checks, not exact-string or snapshot pins, so the grader measures behavior rather than incidental formatting."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "In Account settings, when the user cannot change their email (e.g. realm_email_changes_disabled is true), the change-email button (existing element `#change_email_button`) must be hidden rather than disabled: it gets the codebase-standard `hide` CSS class added; when the user can change their email, the `hide` class must be absent (the button no longer uses the `disabled` property to convey this state)."
  ],
  "reason": "The test binds only to the pre-existing DOM id `#change_email_button` and the existing `cursor-text` label convention; the sole new binding is the state mechanism change from prop('disabled') to the `hide` class. That is a legitimate product/UX requirement a ticket would state ('hide the button instead of disabling it'), and `hide` is the established codebase convention for hidden elements \u2014 the same test file already asserts it on the avatar upload button. None of the fix's genuinely internal choices (new `#email_field_container` id, tippy target, status-element hiding, message wording) are asserted by the test. With the one contract item in the brief, the test grades behavior, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue enumerates concrete UI changes (modal explanatory text, confirmation-notice placement, disabled text field + pencil edit button, hide-when-unpermitted, tooltip over the field), and the evidence plus interface requirements pin down the exact observable contract: #change_email_button toggles the 'hide' class instead of the 'disabled' property via update_email_change_display(), with cursor-text label behavior unchanged. Together these are determinate and checkable."
}
