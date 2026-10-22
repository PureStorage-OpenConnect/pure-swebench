# ZT-18782f3aad74 -- message_view: Allow marking messages as read in `/near/` narrows.

- lang: web   issue: #37342   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/18782f3aad74c5822746d3e3fb4609a43b371dc4
- f2p: web/tests/filter.test.cjs
- p2p: web/tests/message_list.test.cjs, web/tests/message_view.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavioral bug fix / well-specified improvement",
  "reason": "This is a behavioral change to the web client's mark-as-read logic for /near/ narrows, tied to a real issue with a clear specification. It modifies observable behavior through pre-existing interfaces (Filter.can_mark_messages_read, allow_use_first_unread_when_narrowing, MessageList reading state) that existing node tests already exercise, so a hidden test can assert the new behavior without relying on refactors, docs, migrations, version gates, or schema bookkeeping. None of the drop criteria apply."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "The hidden test only changes expected return values of the pre-existing Filter.can_mark_messages_read() method in existing test cases, asserting the new behavior (near-conversation views can mark messages read) through an interface that exists at the base commit. It does not reference any symbol, method, option, or string introduced by the fix (e.g., maybe_resume_reading_for_near_view, near_view_reading_gate_pending), so a solver is not forced to reproduce the author's naming choices."
}
