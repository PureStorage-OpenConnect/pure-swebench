# ZT-693c3347e477 -- typeahead: Improve channel sort priorities in sort_streams.

- lang: web   issue: #36370   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/693c3347e477fc47863b616e38102c3cf3f59d22
- f2p: web/tests/typeahead_helper.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavioral bug fix / small well-specified improvement",
  "reason": "The change alters observable sorting behavior in compare_by_activity/sort_streams: archived channels now sort below unarchived ones, and subscribed channels are reordered by pinned, then recent activity, then muted status (previously muted status came first). This is testable through the pre-existing typeahead_helper interface with node tests asserting sort order, and none of the drop criteria (refactor, i18n, docs, deps, version-gating, etc.) apply."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "The test exercises only pre-existing public API: it calls th.sort_streams() on the already-required typeahead_helper module and asserts on the resulting order of stream names. The stream properties it constructs (stream_id, name, subscribed, is_archived) are all part of Zulip's existing stream data model at the base commit \u2014 is_archived is a long-standing field for archived channels, not something the fix introduces. The fix itself only reorders comparison logic inside the existing compare_by_activity function using the existing prefer_true helper, adding no new symbols, kwargs, or strings for the test to reference. The assertions (archived channels sort below unarchived, subscribed above unsubscribed within each group, muted-but-active above inactive) are user-visible behavioral outcomes any correct solution must produce, regardless of implementation naming."
}
