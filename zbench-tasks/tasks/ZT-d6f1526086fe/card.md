# ZT-d6f1526086fe -- transfer: Upload thumbnails for image files.

- lang: py   issue: #35029   tier: B
- fix: https://github.com/zulip/zulip/commit/d6f1526086fe2e4cebe6871dfe1609cd7f36705e
- f2p: zerver.tests.test_transfer.TransferUploadsToS3Test.test_transfer_message_files
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real production bug (S3 migration tool silently drops thumbnails) with a deterministic outcome-based grader: the test uploads an image with a known thumbnail format, runs the transfer, and asserts the thumbnail object exists in the mocked S3 bucket with byte-for-byte content matching the local file, plus bucket object count fails-before (2) / passes-after (4). Assertions target observable behavior (bucket contents, metadata), not exact log strings or snapshots."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test exercises only pre-existing interfaces at the base commit: upload_message_attachment, transfer_message_files_to_s3, ThumbnailFormat and the thumbnail_formats helper, the established local thumbnail path ({LOCAL_FILES_DIR}/thumbnail/{path_id}/{WxH}.{ext}), and the established S3 thumbnail key convention (thumbnail/{path_id}/{format}) with no user metadata \u2014 the same layout the S3 backend already used for thumbnails, verified at parent commit ad915679a. The assertions (object count, bytes match, metadata) are user-visible outcomes of correctly transferring thumbnails into the location the S3 backend reads from; no new names, log phrasings, or internal helpers are pinned."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_transfer.TransferUploadsToS3Test.test_transfer_message_files"
  ],
  "reason": "Both hunks modify the body of a single existing test method in class TransferUploadsToS3Test. The method name isn't visible in the diff context, but the current Zulip source shows the method containing the upload_message_attachment/transfer_message_files_to_s3 logic (immediately preceding test_transfer_emoji_to_s3) is test_transfer_message_files. The import change and the trailing context line for test_transfer_emoji_to_s3 don't constitute test modifications."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the defect (transfer_uploads_to_s3 ignores the thumbnail/ tree when migrating local storage to S3) and the evidence pins down the exact observable outcome: thumbnails on disk at LOCAL_FILES_DIR/thumbnail/<path_id>/<format> must appear in the uploads bucket at thumbnail/<path_id>/<format> with identical bytes and empty user metadata, while originals keep realm_id/user_profile_id metadata. That is a determinate, checkable specification."
}
