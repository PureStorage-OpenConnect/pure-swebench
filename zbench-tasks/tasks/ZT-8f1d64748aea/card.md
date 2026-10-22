# ZT-8f1d64748aea -- import_util: Filter out stale records from failed parallel downloads.

- lang: py   issue: #39391   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/8f1d64748aea507c850b98cd221c617d4d2ffdda
- f2p: zerver.tests.test_microsoft_teams_importer.MicrosoftTeamsImporterIntegrationTest.test_imported_channel_messages, zerver.tests.test_microsoft_teams_importer.MicrosoftTeamsImporterIntegrationTest.test_imported_channels, zerver.tests.test_microsoft_teams_importer.MicrosoftTeamsImporterIntegrationTest.test_imported_users
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavioral bug fix",
  "reason": "Fixes a real bug (labeled 'bug') where the Slack/Teams importers write attachment and upload records for files whose parallel download failed, leaving orphaned records in the export. The fix adds observable filtering behavior (scrub_missing_upload_records_after_download) exercised through the pre-existing import conversion flow, so a hidden test can assert on converted output records vs. files on disk. Small, well-scoped diff; none of the drop criteria (not a refactor, revert, docs, i18n, type-only, dep bump, test-only, or version/time-gated change) apply. 2026-08-17 update: the brief previously described only the Slack importer (matching the issue's own title and body), but the hidden f2p tests are entirely in test_microsoft_teams_importer.py and the real fix touches microsoft_teams.py as well as slack.py. The smoke run showed 0/10 models touching microsoft_teams.py, because no version of the brief had named it. Rewrote the problem statement to name both importers and require the fix in each."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "The hidden test exercises only pre-existing interfaces: it runs microsoft_teams.do_convert_directory with a mocked failed download added to the existing responses fixture setup, then inspects both standard export artifacts (uploads/records.json and attachment.json's zerver_attachment) to verify every record points to a file that actually exists on disk. It never imports or references the new symbols (scrub_missing_upload_records_after_download, ScrubbedRecords) introduced by the real fix. A solver could satisfy the test with any implementation that avoids or removes orphaned records after failed downloads, in either importer \u2014 the test checks user-visible output-state behavior, not the author's specific API. The rewritten problem statement names zerver/data_import/microsoft_teams.py as the importer that must be fixed (since that is what the hidden tests exercise) without dictating a helper name or requiring the shared-helper design the real fix happened to use."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_microsoft_teams_importer.MicrosoftTeamsImporterIntegrationTest.test_imported_users",
    "zerver.tests.test_microsoft_teams_importer.MicrosoftTeamsImporterIntegrationTest.test_imported_channels",
    "zerver.tests.test_microsoft_teams_importer.MicrosoftTeamsImporterIntegrationTest.test_imported_channel_messages"
  ],
  "reason": "The diff does not add or modify any test_* method directly; it changes the mock_microsoft_graph_api_calls decorator (adding a 400-status failed download response) and adds subTest assertions to the convert_microsoft_teams_export_fixture helper. Both are exercised only via do_import_realm_fixture, which is called by exactly three test methods in MicrosoftTeamsImporterIntegrationTest: test_imported_users, test_imported_channels, and test_imported_channel_messages (verified against the call sites in zerver/tests/test_microsoft_teams_importer.py)."
}
