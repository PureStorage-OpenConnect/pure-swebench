# ZT-cc39b6860b1a -- email_change: Use HTML error for user deactivated error.

- lang: py   issue: #20227   tier: B
- fix: https://github.com/zulip/zulip/commit/cc39b6860b1abd128b641572bb5e79da6ce90ffb
- f2p: zerver.tests.test_email_change.EmailChangeTestCase.test_change_email_deactivated_user_realm
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix / UX improvement",
  "reason": "Real behavior change: deactivated-user email-change confirmation now returns a rendered HTML error page (401) instead of a JSON error. The hidden test grades observable outcomes deterministically \u2014 status code 401 and presence of the error page title substring \u2014 not an exact full-output snapshot, so it fails before and passes after the change without brittleness."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "When a deactivated user opens an email-change confirmation link, instead of a JSON error the server must return a rendered, user-facing HTML error page with HTTP status 401 whose page title is \"Account is deactivated\" (rendered in the standard page-title format as \"Account is deactivated | Zulip\")."
  ],
  "reason": "The 401 status assertion already existed at the base commit; the only new binding is the user-visible error page title string 'Account is deactivated | Zulip'. That is user-facing message wording a ticket would legitimately pin (the removed TODO comment itself asks for a user-facing error). The test does not bind to the template path, context variables, or any internal helper names, so with the title requirement in the brief the test grades behavior, not name-guessing."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_email_change.EmailChangeTestCase.test_change_email_deactivated_user_realm"
  ],
  "reason": "The hunk adds two lines (an error_page_title assertion) inside an existing test whose context \u2014 generate an email-change activation_url, do_deactivate_user, expect 401, then do_reactivate_user \u2014 matches the body of EmailChangeTestCase.test_change_email_deactivated_user_realm in zerver/tests/test_email_change.py, verified against the upstream file. Only that one method is modified; no tests are added."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the intended approach (raise UserDeactivatedError with a user-facing notice rather than a bare JSON error), and the evidence pins down the checkable outcome: HTTP 401 plus an HTML page titled 'Account is deactivated | Zulip' when a deactivated user visits the email-change confirmation link. That is determinate enough for independent engineers to build compatible implementations."
}
