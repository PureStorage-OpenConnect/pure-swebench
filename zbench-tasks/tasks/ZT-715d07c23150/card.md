# ZT-715d07c23150 -- api: Add administrator endpoint for updating user status.

- lang: py   issue: #33139   tier: B
- fix: https://github.com/zulip/zulip/commit/715d07c2315093c3e4d90cdd48b7d915e7ad2d47
- f2p: zerver.tests.test_user_status.UserStatusTest.test_endpoints
- p2p: zerver.tests.test_presence, zerver.tests.test_urls

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature (API endpoint)",
  "reason": "Adds a real, plausibly-assigned API feature: an admin-only POST endpoint at users/<id>/status for setting another user's status. The hidden test grades observable behavior deterministically \u2014 permission errors ('Insufficient permission', 'No such user'), validation errors, emitted user_status events, and resulting status state \u2014 via short, targeted assertions rather than pinned snapshots or exact long-format output. Fail-before/pass-after is clear since the route returns 405/404-style failure without the change."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "A new API endpoint POST /json/users/{user_id}/status lets a realm administrator update another user's status; it accepts the same request parameters as the existing POST /json/users/me/status endpoint (status_text, emoji_name, emoji_code, reaction_type, away) with identical validation, whitespace-trimming, emoji-fill, and error-message semantics.",
    "Requests to the new endpoint for a nonexistent user_id must fail with the standard error message 'No such user' (the same wording already used by existing user-by-id endpoints at the base commit).",
    "Requests by a non-administrator targeting another user must fail with the standard error message 'Insufficient permission' (the same wording already used by existing admin-only user endpoints at the base commit).",
    "A successful update through the new endpoint must emit the pre-existing 'user_status' event schema with user_id set to the TARGET user (not the acting administrator), and the target user's status as returned by GET /json/users/{user_id}/status must reflect the change.",
    "Setting away=true through the new endpoint must apply the existing deprecated away semantics to the TARGET user, i.e. set that user's presence_enabled setting to False (matching the documented behavior of POST /users/me/status)."
  ],
  "reason": "The test exercises only HTTP-level surface: a new URL, request fields identical to the existing /users/me/status endpoint, user-facing error strings, and the pre-existing user_status event schema observed via the standard event-capture harness. The only new names it binds to are the endpoint path and its admin semantics, which a ticket would legitimately dictate; every error string ('No such user', 'Insufficient permission', 'Client did not pass any new values.', emoji validation messages, the 60-char limit message) and every event/response field already exists at the base commit for the /users/me/status flow. No private helpers, internal call signatures, or mock targets from the reference fix (e.g. the view function name update_user_status_admin) appear in the test, so a solver handed the contract above would be graded on behavior, not name-guessing."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_user_status.UserStatusTest.test_endpoints"
  ],
  "reason": "The diff modifies only two methods in UserStatusTest: the helper update_status_and_assert_event (not a test method \u2014 no test_ prefix, so not a runnable target) and test_endpoints, which gains the iago setup line and the large appended block at the end of the file (the 8-space-indented additions in the final hunk continue test_endpoints' body, exercising the new /json/users/{id}/status endpoint). So the single test target is zerver.tests.test_user_status.UserStatusTest.test_endpoints."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the product goal (admins setting other users' status via the API), and the expected-behavior evidence pins down every observable detail: the endpoint path, the exact error messages for missing users, insufficient permission, empty payloads, emoji parameter combinations, and overlong status_text, plus the whitespace-trimming, emoji fill/clear behavior, event user_id semantics, GET reflection, and the away \u2192 presence_enabled side effect. This is concrete enough that two independent implementations would be compatible."
}
