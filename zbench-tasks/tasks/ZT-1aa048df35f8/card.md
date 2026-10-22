# ZT-1aa048df35f8 -- channel_email: Make sender configurable when generating channel email.

- lang: web   issue: #31566   tier: B
- fix: https://github.com/zulip/zulip/commit/1aa048df35f81d6c16aa407d5e9bca5c1c5c8df3
- f2p: web/tests/people.test.cjs
- p2p: web/tests/stream_edit.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real feature work (configurable sender for channel email generation) spanning people.ts and stream_edit.ts \u2014 a plausible assigned engineering task with observable behavior. The hidden test grades deterministic data-layer behavior (Email Gateway bot registered via add_cross_realm_user, retrievable by email, included in get_bot_ids) using targeted asserts, not snapshots or pinned long strings. No format-brittleness, no version/time gating, not a rename/revert/docs-only change."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "Every assertion in the test diff uses interfaces that exist at the base commit (add_cross_realm_user, get_bot_owner_user, get_active_human_count, get_by_email, get_bot_ids); the new email_gateway_bot fixture is plain test data fed through the pre-existing cross-realm-user API. The test never touches the fix's new surface (people.EMAIL_GATEWAY_BOT, the full_name matching branch, or the stream_edit modal changes), so a solver need not guess any author-invented names."
}

## screen: statement
{
  "sufficient": true,
  "why": "The GitHub issue specifies the UI (selector label, option set and ordering, default) and the permission-gating rules concretely, including the backward-compatibility question it raises. The expected-behavior evidence shows the observable requirement that the Email Gateway bot be present client-side as an ownerless cross-realm bot (found by email, listed among bot IDs, excluded from human counts, accessible under restricted user-access settings), which the brief states as product requirements. Together these define a determinate, checkable outcome without referencing tests, PRs, or fixes."
}
