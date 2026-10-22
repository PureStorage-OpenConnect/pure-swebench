# Realm import must produce all avatar image renditions (missing standard-size `.png` causes broken avatars)

## Context

Zulip supports exporting a realm (organization) and importing it into another server — for example, migrating an organization from Zulip Cloud to a self-hosted installation. User avatars are part of this data.

For each user with an uploaded avatar, Zulip stores the avatar in the avatars storage backend (local disk or S3) under a per-user base path (the value computed by `user_avatar_path(user_profile)`). Three objects are expected to exist under that base path:

- `<base>.original` — the originally uploaded image, unmodified;
- `<base>.png` — the standard-size avatar rendition served in most views;
- `<base>-medium.png` — the medium-size rendition.

## Current (buggy) behavior

After importing a realm export, some users' avatars render as the browser's broken-image icon in views that use the standard-size avatar. Inspecting the uploads storage on the importing server shows that for an affected user, `<base>.original` and `<base>-medium.png` exist, but `<base>.png` is missing. In other words, the import pipeline does not reliably (re)generate the full set of avatar renditions from the imported original.

This was reported when importing a Zulip Cloud (`*.zulipchat.com`) export into a self-hosted Zulip Server 11.x installation, but the defect is in the realm import logic itself.

## Required behavior

After a realm import completes, for every imported user profile that has an uploaded avatar, all three avatar objects must exist and be retrievable from the avatars storage backend:

1. `<base>.original` — must contain exactly the original image bytes from the export;
2. `<base>.png` — the standard-size thumbnail, generated from the original;
3. `<base>-medium.png` — the medium-size thumbnail, generated from the original;

where `<base>` is the path returned by `user_avatar_path()` for the imported user on the destination server.

Concretely, the import process must regenerate/write both thumbnail renditions (`.png` and `-medium.png`) from the imported `.original` file, rather than depending on which rendition files happened to be present in the export. This must hold for both storage backends (local file uploads and S3); on S3, a GET of each of the two thumbnail objects must succeed (HTTP 200).

Once this holds, avatars for imported users render correctly in all views instead of showing a broken-image icon.

## Scope notes

- The fix belongs in the realm import pipeline (the code under `zerver/lib/import_realm.py` and/or the avatar/thumbnailing helpers it uses), not in a one-off repair script.
- Do not alter the on-disk naming scheme (`.original`, `.png`, `-medium.png`) or the meaning of `user_avatar_path()`.
- The `.original` object must remain byte-for-byte identical to the exported original; only the derived renditions are (re)generated.

## Interface requirements

(none)
