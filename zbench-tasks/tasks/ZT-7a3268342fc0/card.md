# ZT-7a3268342fc0 -- export: Export `zerver_submessage` table.

- lang: py   issue: #36150   tier: B
- fix: https://github.com/zulip/zulip/commit/7a3268342fc0ccc317d68689f656f5773d688854
- f2p: zerver.tests.test_import_export.RealmImportExportTest.test_import_message_edit_history
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix (missing data in realm/single-user export)",
  "reason": "Real engineering task: the zerver_submessage table (poll/todo widget data) was silently dropped from exports, so imported realms lost widget content. The hidden test grades observable outcomes deterministically \u2014 it sends real /todo and /poll messages, exports, imports into a new realm, and checks the submessages exist with matching sender and semantically-equal content (orjson.loads dict comparison, assertHTMLEqual for rendered content), not raw snapshots. The single-user export checker does pin one small content string, but that string is the deterministic stored SubMessage.content produced by the widget parser for a fixed input, not incidental formatting \u2014 this is outcome-graded, not brittle."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test verifies behavior entirely through pre-existing interfaces: the SubMessage model and zerver_submessage table (which the fix merely un-excludes from export), DB_TOPIC_NAME, /todo and /poll widget message flows, and the standard export record format produced by the existing make_raw convention. Assertions check user-visible round-trip outcomes (SubMessage rows exist post-import with remapped FKs, content and rendered_content preserved; single-user export contains the user's submessage records with the model's own field names). No new function, config, mapping key, or module introduced by the fix is referenced, so any correct implementation passes without name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the concrete defect (zerver_submessage in NON_EXPORTED_TABLES breaks polls/to-do lists after import) and the evidence pins down observable outcomes: round-trip equality of submessage content, sender remapping, rendered_content equivalence, and the exact single-user export record shape. This is determinate and checkable without revealing tests."
}
