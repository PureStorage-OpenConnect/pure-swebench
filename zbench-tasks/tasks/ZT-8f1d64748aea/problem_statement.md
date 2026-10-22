## Zulip's data importers write upload and attachment records for files whose download fails

### Observed behavior

Zulip has more than one importer that brings data in from a third-party chat tool (for example, Slack and Microsoft Teams) into a Zulip export that can then be loaded with `do_import_realm`. **Both of these importers share the same bug.**

Each importer downloads a workspace's uploaded files and, separately, writes JSON records describing those files (an entry in `uploads/records.json`, and — for the Slack importer — a matching entry in `attachment.json`) into the export it produces. Regardless of which importer is used, a record gets written for every file the importer encounters, even if that particular file's download ends up failing (for example, because the remote host returns a 404 for the file's URL by the time the importer runs). When a download fails, the importer still emits a row for that file, even though no corresponding file exists on disk in the export.

When the resulting export is imported with `do_import_realm`, `import_uploads` trips over these orphan records and raises a `FileNotFoundError`, causing the entire realm import to fail.

### Expected behavior

For **each** importer that has this pattern (at minimum, the Slack importer in `zerver/data_import/slack.py` and the Microsoft Teams importer in `zerver/data_import/microsoft_teams.py`), upload records (and, where the importer builds them, attachment records) should only be written for files whose download actually succeeded. An export produced from source data containing dead file links should import cleanly, with the failed files simply omitted from both the upload records and any attachment records that reference them.

This is not a one-off fix to a single file. Both importers independently build up a list of file records and a separate list of attachment records before or during the download step, and both need the same corrective step applied after their downloads finish. Fixing only one importer leaves the other producing invalid exports whenever one of its file downloads fails.

### Relevant background

The difficulty is that the download is decoupled from the record writing, in both importers. In Slack's `process_message_files`, the call to `do_download_and_export_upload_file` looks synchronous, but that function is actually a closure returned by `run_parallel_queue`: calling it merely enqueues the download onto a `ProcessPoolExecutor` and returns immediately, with the actual HTTP fetch happening later in a worker process. So at the point where the loop in `process_message_files` appends to `uploads_list` and calls `build_attachment`, the download has not yet run, and the caller has no way to condition record creation on the download's outcome. The record only becomes provably valid once the corresponding file has (or has not) actually landed on disk in the export's `uploads/` directory.

The Microsoft Teams importer (`zerver/data_import/microsoft_teams.py`) has the same structure: its message-conversion step also uses `run_parallel_queue` to dispatch file downloads to worker processes while accumulating a list of upload records synchronously, before those downloads have necessarily completed. (Its attachment records happen to be built only inside the download worker itself, after a successful download, so — unlike Slack — only its upload-records list, not a separate attachment-records list, can end up with orphaned entries; check the code to confirm this before relying on it.)

A realistic approach is a post-processing scrub, applied in each importer after all of that importer's downloads have completed: filter the upload records (and, where applicable, attachment records) down to the files that are actually present on disk in the export's `uploads/` directory, by path. Because both importers need the identical check, consider writing it once in `zerver/data_import/import_util.py` (which both importers already import from) and calling it from each importer's conversion flow, rather than duplicating the filtering logic — but any correct fix, in either importer or in a shared location, is acceptable as long as both importers end up producing only records for files that actually downloaded successfully.
