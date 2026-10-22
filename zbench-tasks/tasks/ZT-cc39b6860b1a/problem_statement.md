# Improve the email-change confirmation page for deactivated users

## Context

Zulip lets a user change their account email address. The flow sends a confirmation email to the new address containing an activation link (a `/accounts/confirm_new_email/<confirmation_key>` style URL). Visiting that link confirms the change and shows a confirmation page.

## Current behavior

If the user's account has been **deactivated** between requesting the email change and clicking the confirmation link, opening the link does not produce a reasonable user-facing result. The deactivated-account condition is surfaced as a raw JSON API-style error rather than a rendered page a person clicking a link in their email client can understand.

## Required behavior

When a deactivated user opens an email-change confirmation link:

- The server must respond with HTTP status **401**.
- The response body must be a rendered, user-facing **HTML error page** (not a JSON error payload), styled consistently with Zulip's other standalone error/notice pages.
- The page's HTML `<title>` must be **"Account is deactivated"**, rendered in Zulip's standard page-title format, i.e. the document title reads exactly `Account is deactivated | Zulip`.
- The page content should tell the user their account has been deactivated (matching the tone/structure of Zulip's existing error pages for cases like invalid or expired confirmation links).

The recommended approach is to raise the existing deactivated-user error (`UserDeactivatedError`) in the confirm-email-change view and ensure that, in this browser-facing flow, that error is rendered as the HTML error page described above instead of the JSON error normally produced for API endpoints.

All other outcomes of the confirmation flow must be unchanged:

- An **active** user opening a valid confirmation link still gets the normal email-change confirmation behavior.
- If the account is **reactivated** afterwards, the user can log in and use the site normally; the deactivation error page applies only while the account is deactivated.
- Invalid or expired confirmation keys keep their existing behavior.

## Interface requirements

- When a deactivated user opens an email-change confirmation link, instead of a JSON error the server must return a rendered, user-facing HTML error page with HTTP status 401 whose page title is "Account is deactivated" (rendered in the standard page-title format as "Account is deactivated | Zulip").
