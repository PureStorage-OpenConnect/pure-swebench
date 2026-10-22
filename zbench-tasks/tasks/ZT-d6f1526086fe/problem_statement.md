# `transfer_uploads_to_s3` must also migrate generated thumbnails

## Context

Zulip can store user uploads either on the local filesystem (under `settings.LOCAL_UPLOADS_DIR` / `settings.LOCAL_FILES_DIR`) or in S3. The management command `./manage.py transfer_uploads_to_s3` (implemented in `zerver/lib/transfer.py`) exists to migrate an installation from local storage to S3. It transfers avatars, emoji, and message attachments.

When a user uploads an image as a message attachment, Zulip also generates one or more thumbnails for it. With local storage, the original file lives at `<LOCAL_FILES_DIR>/<path_id>` (where `path_id` is the attachment's `Attachment.path_id`, e.g. `<realm_id>/<random>/<filename>`), and each generated thumbnail lives at `<LOCAL_FILES_DIR>/thumbnail/<path_id>/<thumbnail_format_name>` (e.g. `.../thumbnail/<path_id>/100x75.webp`, where the last component is the string form of the `ThumbnailFormat`, such as `<width>x<height>.<extension>` with an `-anim` suffix for animated formats). With S3 storage, the same layout is used as object keys in the uploads bucket: originals at `<path_id>` and thumbnails at `thumbnail/<path_id>/<thumbnail_format_name>`.

## Current (broken) behavior

`transfer_message_files_to_s3` iterates over `Attachment` rows and uploads only the original file for each attachment to the S3 uploads bucket. It never looks at the local `thumbnail/` tree. After migrating a server from local storage to S3, all previously generated thumbnails are missing from the bucket, so existing image previews are broken (the objects at `thumbnail/<path_id>/...` don't exist).

## Required behavior

When transferring message attachments to S3, the command must also transfer every thumbnail that exists on local disk for each attachment:

1. For each `Attachment`, after (in addition to) uploading the original file to the uploads bucket at key `<path_id>`, check the local directory `<LOCAL_FILES_DIR>/thumbnail/<path_id>/`. If it exists, upload each file `<thumbnail_format_name>` found there to the uploads bucket at key `thumbnail/<path_id>/<thumbnail_format_name>`.
2. The uploaded thumbnail object's body must be byte-for-byte identical to the local thumbnail file.
3. The original attachment objects must keep their existing user-defined S3 metadata: `realm_id` (the attachment's realm id, as a string) and `user_profile_id` (the uploading user's id, as a string). Thumbnail objects must be uploaded with **no** user-defined metadata (an empty metadata dict), matching how Zulip's S3 backend stores thumbnails it generates directly.
4. Thumbnail objects should be uploaded with an appropriate content type for the thumbnail file (thumbnails are typically `.webp`), consistent with how the S3 upload backend stores freshly generated thumbnails.
5. Attachments that have no thumbnails (e.g. plain text files) must continue to transfer exactly as before — no `thumbnail/` objects are created for them and the transfer must not fail because the thumbnail directory is absent.
6. Concretely: after running the transfer on a server with two text attachments and one image attachment that has one generated thumbnail (`100x75.webp`), the uploads bucket must contain exactly 4 objects — the three originals at their `path_id` keys plus one object at `thumbnail/<image_path_id>/100x75.webp`.

The transfer should remain parallelized/batched the same way the rest of the command is (it accepts a process count) and should continue logging its progress at INFO level.

## Scope

Only the message-attachment transfer path needs to change (`transfer_message_files_to_s3` and any helper it uses in `zerver/lib/transfer.py`). Avatar and emoji transfers already handle their own resized variants and are out of scope.
