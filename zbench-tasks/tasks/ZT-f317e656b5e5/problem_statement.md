## S3 uploads backend: tus pre-finish hook stalls ~30 seconds per upload on MinIO because it holds an open GET on the object it then self-copies

### Observed behavior

On a self-hosted Zulip using the S3 uploads backend pointed at MinIO (single node, single drive, no versioning, no SSE on the uploads bucket), every file upload larger than roughly 100 KB made through the web app (the tus/tusd upload path) hangs for a constant ~30 seconds between the upload transfer completing and the file URL being inserted into the compose box. The upload progress bar finishes quickly and the object is fully present in the bucket, but the client then waits while tusd blocks on the pre-finish hook response. The delay is a constant ~30 s regardless of file size (a 2.3 MiB file and much larger files behave the same), while small files (~100 KB) complete in a few hundred milliseconds.

`server.log` shows the pre-finish hook request taking 30.5 s with almost no database time:

```
2026-07-15 10:31:30.744 INFO [zr] 127.0.0.1 POST 200 30.5s (db: 4ms/4q) /api/internal/tusd (9@root via Go-http-client)
2026-07-15 10:32:45.594 INFO [zr] 127.0.0.1 POST 200 391ms (db: 5ms/5q) /api/internal/tusd (20@root via Go-http-client)
```

`mc admin trace -v` on MinIO shows the corresponding self-CopyObject (on the 2.3 MiB object) spending essentially all of its time waiting inside MinIO rather than transferring data:

```
[REQUEST s3.CopyObject] PUT /chat-uploads/2/.../IMG_9299.mp4
X-Amz-Copy-Source: chat-uploads/2/.../IMG_9299.mp4
X-Amz-Metadata-Directive: REPLACE
[RESPONSE] [ Duration 30.161673s TTFB 30.161628914s ↑ 274 B ↓ 232 B ]  200 OK
```

Replaying the exact same self-CopyObject with boto3 outside the hook (against both a single-PUT object and a multipart object created by tusd) completes in 0.05–0.3 s. The copy itself is fine; it is only slow when executed by the hook, concurrently with a request the hook itself opened.

### Root cause

In `handle_upload_pre_finish_hook` in `zerver/views/tusd.py`, the hook calls `attachment_source(path_id)` and passes the result to `maybe_add_charset(content_type, file_data)` before performing a self-`CopyObject` on the same object (`copy_from` with `MetadataDirective="REPLACE"`).

`S3UploadBackend.attachment_source()` in `zerver/lib/upload/s3.py` eagerly issues `Object(path_id).get()` and returns the unread `StreamingBody`. `maybe_add_charset()` only consumes that stream when the content type is `text/plain`; for any other content type it returns immediately, leaving the streaming body neither read nor closed. The hook then performs the self-copy on the same object while its own GET is still in flight.

MinIO holds a read lock on an object for the duration of an active GET. If the object fits into the socket buffers (small files), the server finishes sending immediately, the lock is released, and the copy is fast — matching the observed 391 ms case. If it does not fit (roughly >100 KB), the GET remains active because the body is never read, and the write lock needed by CopyObject blocks until MinIO's write deadline terminates the idle reader after ~30 s — matching the constant, size-independent stall. AWS S3 does not lock this way, which is presumably why the problem has gone unnoticed there.

### Expected behavior

Uploads through the tus path should finalize promptly (well under a second on MinIO for typical files) regardless of file size. The pre-finish hook should not hold an open, unread GET on the object while it issues the self-CopyObject on that same object.

Two behaviors must be preserved by any change here:

1. Charset detection for `text/plain` uploads via `maybe_add_charset()` must continue to work.
2. Thumbnailing must continue to work. Note that simply closing the streaming body immediately after `maybe_add_charset()` is not sufficient: the same `StreamingSourceWithSize` is later consumed by `create_attachment()` → `maybe_thumbnail()`, which would then read from a closed stream, causing images to be treated as invalid and losing previews.
