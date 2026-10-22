# ZT-e4a85fd7508f -- compose: Clear preview area in clear_compose_box instead of do_post_send_tasks.

- lang: web   issue: #33245   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/e4a85fd7508fcde13c85790767839c5df77c5040
- f2p: web/tests/compose.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavioral bug fix (web client)",
  "reason": "Small, well-specified fix for a real user-visible bug: sending from preview mode prematurely switched the compose box to edit mode. Moving clear_preview_area() into clear_compose_box changes observable compose-box state through pre-existing exported functions, which a hidden node test can assert directly (e.g., that clear_compose_box clears the preview area / do_post_send_tasks no longer does). None of the drop criteria apply \u2014 it's not a refactor, revert, i18n, docs, type-only, dep bump, test-only, or version/time-gated change."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "All symbols the test uses exist at the base commit: compose.clear_compose_box and clear_preview_area are pre-existing exports in web/src/compose.ts, and fake_compose_box.assert_preview_mode_is_on/off already exist in web/tests/lib/compose_helpers.cjs (the fix commit e4a85fd7 doesn't touch that helper file). The test asserts behavior/state through these pre-existing interfaces \u2014 preview stays on after finish() and clears when clear_compose_box() runs \u2014 matching the issue's described outcome of not prematurely exiting preview mode before send success. No fix-introduced symbol, module, or invented string is referenced."
}
