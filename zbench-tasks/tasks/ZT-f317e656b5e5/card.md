# ZT-f317e656b5e5 -- upload: Don't hold a read open on S3 objects during self-copy.

- lang: py   issue: #39752   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/f317e656b5e5070e2206d66b58bdcefe630d64d5
- f2p: zerver.tests.test_tusd.TusdPreFinishTest.test_s3_upload_no_read_open_during_self_copy
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavioral bug fix",
  "reason": "Genuine performance/correctness bug in the tus pre-finish hook: an open GetObject read was held across a self-copy, stalling ~30s on lock-per-object S3-compatible backends like MinIO. The fix changes observable behavior through existing interfaces \u2014 attachment_source is only opened when needs_charset_detection is true, the reader is closed via try/finally even on error, and a fresh source is opened after the copy. A hidden test can verify this behaviorally (e.g., asserting no object read is opened for non-text content types, or that the source is opened/closed around rather than across the copy) without touching migrations, version gates, or schema bookkeeping. None of the drop criteria apply."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "Every symbol the test touches exists at the base commit: get_upload_backend, sanitize_name, generate_message_upload_path, S3UploadBackend, TusUpload, create_s3_buckets are all in the pre-existing import surface (the code diff itself shows zerver/views/tusd.py already importing get_upload_backend and calling attachment_source(path_id) in the removed lines, so the mock target zerver.views.tusd.attachment_source and the StreamingSourceWithSize interface with .size/.reader()/.read()/.close() predate the fix). The test does not import needs_charset_detection or any other symbol the fix adds, does not assert any new error string, and drives the behavior entirely through the pre-existing /api/internal/tusd endpoint. Its assertions are about observable interaction order \u2014 that no open read of the object spans the self-CopyObject, and that the object is not opened at all when the content type already declares a charset \u2014 which is precisely the user-visible defect described (MinIO-style per-object read locks blocking the copy). The mock-call-order assertion is on the strict side (it also pins that a fresh source is opened after the copy, which would reject an alternative fix that buffered the bytes in memory), but that is behavioral over-specification through existing interfaces, not coupling to invented names from the reference solution."
}
