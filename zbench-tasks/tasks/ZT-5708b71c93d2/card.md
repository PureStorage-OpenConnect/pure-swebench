# ZT-5708b71c93d2 -- recent_view: Add folder filter dropdown.

- lang: web   issue: #37394   tier: B
- fix: https://github.com/zulip/zulip/commit/5708b71c93d23cbc15e31d30fab0c24a5ba59465
- f2p: web/tests/recent_view.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Real, plausibly-assigned feature work (folder filter dropdown in recent conversations) with a deterministic behavioral grader: the hidden test exercises filters_should_hide_row across folder-filter states (any folder, specific folder, uncategorized, DM hiding) and asserts boolean visibility outcomes, which fail before the change and pass after. The added show_folder_filter param assertions are small object-field checks, not brittle full-snapshot or exact-string pins."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The recent view module (web/src/recent_view_ui.ts) must export a function `set_folder_filter_for_tests(value: number)` that sets the recent view's active folder filter to `value`, where `value` is either a channel-folder id or one of the existing `folder_dropdown_widget.FOLDER_FILTERS` sentinels.",
    "The existing exported `clear_for_tests()` in recent_view_ui must also reset the folder filter to its default, `FOLDER_FILTERS.ANY_FOLDER_DROPDOWN_OPTION` (the 'Any folder' state), so that after a reset no row is hidden by folder filtering.",
    "The context object rendered into the `recent_view_filters` template gains a boolean field `show_folder_filter`, whose value is `channel_folders.user_has_folders()` \u2014 true only when the organization has channel folders visible to the user (the existing filter fields filter_unread/filter_participated/filter_muted/filter_pm/search_val/is_spectator are unchanged).",
    "Folder-filter semantics of the existing `filters_should_hide_row(conversation)`: with the default ANY_FOLDER_DROPDOWN_OPTION sentinel active, folder filtering hides nothing; with any non-default folder filter active, all direct-message conversation rows are hidden; with UNCATEGORIZED_DROPDOWN_OPTION active, only channel conversations whose subscription has `folder_id === null` are shown; with a concrete folder id active, only channel conversations whose subscription's `folder_id` equals that id are shown.",
    "The implementation must reuse the pre-existing shared modules rather than reimplementing them: recent_view_ui must import and consult `channel_folders` (for `user_has_folders()`) and `folder_dropdown_widget` (for the `FOLDER_FILTERS` sentinel constants) as part of the folder-filter feature."
  ],
  "reason": "Verified against zulip at base commit a385901 (parent of the reference fix 5708b71): every module the test mocks pre-exists with matching shape \u2014 folder_dropdown_widget exports FOLDER_FILTERS with UNCATEGORIZED=-1 / ANY=-2 (exactly the values the test mocks and passes as raw numbers, so no sentinel guessing), plus create_folder_filter_dropdown_widget and update_tooltip_for_folder_filter; channel_folders exports all four mocked functions; filters_should_hide_row, clear_for_tests, set_filters_for_tests, and the subscription `folder_id` field are pre-existing interfaces. The only new names the test requires are the module export set_folder_filter_for_tests, the template-context field show_folder_filter (pinned by exact-equality assertions in five template tests), the clear_for_tests reset behavior, and \u2014 because Zulip's namespace.cjs fails tests on unused mock_esm mocks \u2014 the requirement to import the two pre-existing shared modules. Each of these is legitimate ticket-dictated contract (a public module export, a UI template field for the new control, and 'reuse the existing shared widget/feature modules'), not private implementation layout, so a solver handed these requirements would be graded on filtering correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue describes the UI requirements (placement, icon, coloring, dropdown options, DM hiding, search-input min width), and the expected-behavior evidence plus interface requirements pin down exact filtering semantics (ANY_FOLDER default hides nothing, concrete folder id matches subscription folder_id, UNCATEGORIZED matches folder_id === null, non-default filters hide DMs), the template context field show_folder_filter driven by channel_folders.user_has_folders(), and the required exported functions and reset behavior. Together these give a determinate, checkable outcome that two engineers could implement compatibly."
}
