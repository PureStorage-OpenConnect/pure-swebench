# Realm import poisons the custom-emoji cache, breaking emoji in imported organizations

## Context

Zulip supports exporting an organization (realm) and importing it into another server (`do_import_realm` in `zerver/lib/import_realm.py`). Custom emoji for a realm are looked up through `get_all_custom_emoji_for_realm` (in `zerver/models/realm_emoji.py`), which caches its result per realm.

## Current (buggy) behavior

During import, channel (stream) descriptions are rendered to HTML (`render_stream_description`) at a point in the import sequence **before** the realm's `RealmEmoji` rows have been imported. The markdown renderer looks up the realm's custom emoji via `get_all_custom_emoji_for_realm`, which at that moment returns an empty set — and that empty result gets stored in the cache for the newly imported realm.

Observable consequences in the imported realm, until the cache entry expires:

1. The realm's custom emoji list appears empty to users, even though the `RealmEmoji` rows were imported into the database.
2. Attempting to re-add an emoji with the same name as an imported one fails with a duplicate-emoji error (the row exists in the database, but the cached, empty listing hides it).
3. Custom emoji used in channel descriptions do not render as emoji images, because they were rendered while the emoji set appeared empty.

## Required behavior

Rework the import flow so that nothing during import populates the custom-emoji cache with stale/empty data. Concretely, immediately after `do_import_realm` completes for a realm that had custom emoji and a channel description referencing one (e.g. description text `Render realm emoji here! :guatemala:`):

1. **Cache/listing correctness.** `get_all_custom_emoji_for_realm(imported_realm.id)` must return one entry per imported `RealmEmoji` row (same count as `RealmEmoji.objects.filter(realm=imported_realm)`), keyed by the emoji's ID (as a string). Each entry's fields must reflect the imported database rows, not stale data:
   - `id` matches the imported `RealmEmoji` row's ID;
   - `name` matches the row's name;
   - `author_id` matches the row's author's user ID (an ID in the imported realm, since user IDs are remapped during import);
   - `source_url` points at the imported realm's emoji storage path — i.e. the URL directory for the emoji file name derived from the imported emoji's ID under the imported realm's ID (of the form `/user_avatars/<imported_realm_id>/emoji/images/...`), not the original realm's path.
2. **Channel description rendering.** A channel whose description contains a custom emoji (e.g. `:guatemala:`) must, in the imported realm, have a `rendered_description` containing the emoji image markup, e.g. `<p>Render realm emoji here! <img alt=":guatemala:" class="emoji" src="/user_avatars/<imported_realm_id>/emoji/images/...` — the `src` must use the **imported** realm's ID.
3. Adding a new custom emoji after import must behave normally: a genuinely new name succeeds, and a name colliding with an imported emoji is a legitimate duplicate (the failure mode where the listing is empty yet duplicate-name additions are rejected must no longer occur).

## Implementation notes

- The fix should ensure that any markdown rendering performed during import that needs the realm's custom emoji happens only after all `RealmEmoji` rows (and their remapped IDs/file paths) are in place — or otherwise avoid/invalidate the premature cache fill. Either ordering the work correctly or flushing the relevant cache after emoji import is acceptable, as long as the post-import guarantees above hold with no time window in which the cache holds an empty emoji set for the imported realm.
- Behavior must hold in a standard import (e.g. with billing disabled), and pre-existing import behavior for other data must be unchanged.
