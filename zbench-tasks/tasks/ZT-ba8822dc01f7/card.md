# ZT-ba8822dc01f7 -- import: Avoid caching realm emoji before it is imported.

- lang: py   issue: #36482   tier: B
- fix: https://github.com/zulip/zulip/commit/ba8822dc01f76bc3828801e97faf3bcf4779c909
- f2p: zerver.tests.test_import_export.RealmImportExportTest.test_get_all_custom_emoji_for_realm_cache_after_import
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real bug: do_import_realm rendered stream descriptions (which calls the caching get_all_custom_emoji_for_realm) before RealmEmoji rows were imported, poisoning the cache and breaking emoji rendering in imported realms. This is a plausible assigned fix with clear fail-before/pass-after behavior. The hidden test grades observable outcomes deterministically: emoji count and cache contents match post-import, per-emoji fields (author, name, source_url path) are correct, and the rendered channel description contains the emoji img markup. It uses assertIn on a short stable HTML fragment and field-level equality checks rather than pinning a full rendered snapshot or exact long string, so it is not brittle format-grading."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test exercises only interfaces that pre-exist at the base commit: check_add_realm_emoji, the stream-description PATCH endpoint, do_import_realm, the RealmEmoji model, and the cached lookup get_all_custom_emoji_for_realm with its established dict fields (id, author_id, name, source_url), plus the long-standing helpers get_emoji_file_name/get_emoji_url \u2014 none of these are created or modified by the code diff, which only reorders internal steps inside do_import_realm (rendering stream descriptions after RealmEmoji import). The assertions target user-visible outcomes: the imported realm's custom-emoji dict is complete/non-stale and channel descriptions render emoji img tags with the correct /user_avatars/<realm_id>/emoji/images/ path. A solver who fixes the cache-poisoning bug by any means (reordering, cache invalidation, deferred rendering) passes without guessing any new names."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue explains the root cause (early render_stream_description caching an empty emoji set via get_all_custom_emoji_for_realm) and its user-visible symptoms, and the regression-test diff pins down concrete, checkable post-import outcomes: correct cached emoji dict contents (count, id, name, author_id, source_url path under the imported realm) and correctly rendered channel descriptions with imported-realm emoji URLs. No interface requirements were provided."
}
