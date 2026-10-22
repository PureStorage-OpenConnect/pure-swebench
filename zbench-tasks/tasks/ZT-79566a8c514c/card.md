# ZT-79566a8c514c -- stream-settings: Add permissions tab for stream settings.

- lang: web   issue: #36523   tier: B
- fix: https://github.com/zulip/zulip/commit/79566a8c514cb78b167f63b33130a8bd9b5f4baa
- f2p: web/tests/settings_org.test.cjs
- p2p: web/tests/hash_util.test.cjs, web/tests/stream_edit.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, plausibly-assigned UI feature: adds a 'Permissions' tab to channel settings with observable behavior changes \u2014 hash_util.validate_channels_settings_hash now accepts 'permissions' as a right-side tab, the toggler gains a new tab key, and save-button/permission-disable logic keys off new containers. These are deterministically gradable in Zulip's node test suite (fail-before/pass-after on hash validation and settings logic). The visible test diff merely adapts jQuery stub selectors to the new '.pill-container.prop-element' behavior rather than pinning long output strings or HTML snapshots, so it is not format-brittle. Not a rename-only or docs change; the selector/container renames accompany genuine behavior changes (tab routing, save-button scoping)."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "Unsaved-changes detection for a settings subsection must identify group-permission setting widgets by selecting elements matching `.pill-container.prop-element` (pill containers that are marked as property elements via the pre-existing `prop-element` class), so that pill containers which are not property elements (e.g., the channel folder widget's pill container) are excluded from save-button change tracking."
  ],
  "reason": "The only test change swaps the DOM query the save-button logic is expected to make: `.pill-container` becomes `.pill-container.prop-element`. Because the test harness resolves find() calls by exact selector string, a solver must use precisely this selector inside the change-detection code, even though a behaviorally equivalent filter (e.g., `.filter('.prop-element')` or reversed class order) would produce the same user-visible result. That makes the exact selector part of what the test grades. However, both CSS classes (`pill-container`, `prop-element`) exist in the templates at the base commit and describe real markup structure \u2014 the selector is the JS-to-template interface, not a private helper name or invented internal field. A ticket could legitimately state the requirement as 'restrict change tracking to prop-element pill containers, queried as `.pill-container.prop-element`', at which point the test grades correctness of the behavior change rather than name-guessing. All other assertions in the test exercise pre-existing save-button behavior through the existing settings_org interfaces, and the remaining code-diff surface (the new 'permissions' tab key, hash value, container classes) is not bound by this test diff."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives a concrete, checkable UI reorganization (new Permissions tab at /permissions with specified contents and ordering, General tab reordering), and the evidence plus interface requirements pin down the one behavioral subtlety: subsection change-detection must select .pill-container.prop-element so non-property pill widgets like the folder picker are excluded. Together these are determinate enough for independent engineers to build compatible implementations."
}
