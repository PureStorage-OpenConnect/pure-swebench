# ZT-8a64940868ec -- message_edit: Fix "(deleted)" not showing for empty edited DMs.

- lang: py   issue: #33305   tier: B
- fix: https://github.com/zulip/zulip/commit/8a64940868ecc70b94ad2fac561e868581be0319
- f2p: zerver.tests.test_message_edit.EditMessageTest.test_edit_message_in_unsubscribed_private_stream
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real bug fix (empty-content DM edits weren't replaced with '(deleted)') with a deterministic hidden test: it exercises the API endpoint and asserts the stored message content equals '(deleted)'. This grades observable behavior, fails before the fix and passes after, and pins no brittle snapshot or incidental formatting."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The added test hits the pre-existing message-edit API (PATCH /json/messages/{id}) with a whitespace-only content edit on a DM and asserts the message content becomes \"(deleted)\" \u2014 the exact sentinel behavior the base commit already exhibits and tests for stream messages. It checks a user-visible outcome through existing interfaces only; it never touches the refactored internals (build_message_edit_request, DirectMessageEditRequest), so any correct fix that makes DM edits honor the empty-content deletion behavior passes."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user-visible defect (DM edited to empty shows nothing instead of '(deleted)'), and the expected-behavior evidence pins down the exact observable contract: PATCH /json/messages/{id} with whitespace-only content on a personal message must succeed and persist the literal content '(deleted)', matching the existing stream-message behavior. That is a determinate, checkable outcome two engineers would implement compatibly."
}
