# Improve the UI for changing your email address in personal settings

## Background

In Zulip's web app, the personal settings area (Settings → Account & privacy, implemented around `web/src/settings_account.*`, with templates under `web/templates/settings/`) shows the user's email address with a "Change your email" button that opens a modal for entering a new address. The display logic for this control lives in `settings_account.update_email_change_display()`, which reacts to whether the user is allowed to change their email (for example, when the realm setting `realm_email_changes_disabled` is true, or the user is otherwise not permitted to edit their email).

Current behavior:

- The email is shown as plain content with a separate "Change your email" button.
- When email changes are not permitted, the button is kept visible but set to `disabled`, and a "email changes are disabled"-style tooltip appears on/next to the disabled button.
- After a user requests an email change, a confirmation notice (telling them to check their inbox to confirm the new address) is displayed in the section heading area.
- The change-email modal gives no up-front explanation of what will happen after submitting.

## Required behavior

### 1. Change-email modal

At the top of the change-email modal, add an explanatory line (translated like other UI strings):

> You will receive a confirmation email at the new address you enter.

### 2. Confirmation notice placement

Move the pending-email-change confirmation notice out of the section heading. It should instead appear as a plain text line directly below the email field. The text of the notice itself must not change — only its placement and presentation (plain text, not a heading-level notice).

### 3. Email display and edit affordance

- Render the user's current email as a **disabled text input field** (read-only display in a text-field control), rather than plain text.
- Next to the field, show an "Edit" button (pencil icon) that opens the existing change-email modal. This replaces the previous full "Change your email" button as the way to open the modal.
- If the user does not have permission to change their email (e.g., `realm_email_changes_disabled` is true, or demo-organization/other restrictions that previously disabled the button), the edit button must **not be shown at all** — hidden, not merely disabled.
- When changes are disabled, the informational tooltip explaining that email changes are disabled must appear when hovering **over the email field itself**, not positioned to the right of where the button was.

### 4. Hidden vs. disabled semantics

The permission state must be conveyed by hiding the control, not by the `disabled` property:

- `update_email_change_display()` must toggle visibility of the change-email button using the codebase-standard `hide` CSS class.
- When the user **cannot** change their email, the button element `#change_email_button` has the `hide` class.
- When the user **can** change their email, `#change_email_button` does not have the `hide` class.
- The button must no longer use the `disabled` property to convey this state.
- The existing behavior of toggling the `cursor-text` class on `label[for='change_email_button']` (present when changes are disabled, absent when allowed) must be preserved.

## Interface requirements

- In Account settings, when the user cannot change their email (e.g. `realm_email_changes_disabled` is true), the change-email button — the existing element with id `change_email_button` — must be hidden rather than disabled: it gets the codebase-standard `hide` CSS class added. When the user can change their email, the `hide` class must be absent. The button no longer uses the `disabled` property to convey this state.

## Notes

- Keep the element id `change_email_button` for the button that opens the modal, even though its visual form changes to a pencil/edit icon.
- Follow existing settings-page patterns for disabled text fields, icon buttons, tooltips, and translated strings so the control matches the rest of the Account settings UI.
