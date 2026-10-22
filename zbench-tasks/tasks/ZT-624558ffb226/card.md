# ZT-624558ffb226 -- import: Fix missing avatar thumbnails.

- lang: py   issue: #37601   tier: B
- fix: https://github.com/zulip/zulip/commit/624558ffb226c101fbbfbad5b7cf6b346452d2c2
- f2p: zerver.tests.test_import_export.RealmImportExportTest.test_import_files_from_s3
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real bug fix in avatar import logic with an observable behavioral outcome: after import, avatar thumbnail objects must exist in the storage bucket. The hidden test asserts existence and retrievability of specific thumbnail keys (deterministic paths derived from the user) rather than pinning rendered output or exact long strings \u2014 it fails before the fix (thumbnails skipped unless importer_should_thumbnail) and passes after, grading behavior not format."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test verifies observable behavior (avatar thumbnail objects present in S3 after import) using only pre-existing interfaces: user_avatar_path() and Zulip's established avatar path suffix conventions ('.original', '.png', '-medium.png'), which are already defined by the upload backend at the base commit. It does not bind to any name, helper, flag, or record field introduced or removed by the fix, so any correct implementation that generates thumbnails during import passes."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_import_export.RealmImportExportTest.test_import_files_from_s3"
  ],
  "reason": "The diff modifies existing assertions inside the S3-backed file import test in RealmImportExportTest (the hunk uses avatar_bucket / boto3 Object calls, which appear only in test_import_files_from_s3, not the local-storage variant). No new test methods are added, so this is the only affected test target."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives the concrete symptom (imported avatars missing the standard `<hash>.png` while `.original` and `-medium.png` exist), and the expected-behavior evidence pins down the checkable outcome: after realm import, `.original` must hold the exact original bytes and both `-medium.png` and `.png` renditions must exist and be retrievable from the storage backend. That is a determinate, verifiable requirement two engineers could implement compatibly."
}
