# ZT-3c1e6ef9951e -- compose: Preserve indentation when continuing lists.

- lang: web   issue: #37737   tier: UNKNOWN
- fix: https://github.com/zulip/zulip/commit/3c1e6ef9951e4043e38a680ffde0721ee8cfc080
- f2p: web/tests/composebox_typeahead.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavioral bug fix",
  "reason": "Well-specified compose-box bug: continuing a list with Shift+Return dropped the indentation of sub-list items. The fix changes observable behavior (preserved indent, correct bullet/number continuation, correct empty-item removal) in existing modules that are covered by Zulip's node unit tests, so a hidden test can assert behavior through pre-existing interfaces. None of the drop criteria (refactor, i18n, docs, deps, test-only, version-gating, CSS) apply."
}

## screen: coupling
{
  "verdict": "clean",
  "reason": "The hidden test exercises only pre-existing interfaces: it sets the textarea value/selection, triggers the existing keydown handler on form#send_message_form, and asserts on behavior via overrides of compose_ui.insert_and_scroll_into_view and setSelectionRange \u2014 all of which are already used by the surrounding test code at the base commit. It never references the new symbol the fix introduces (bulleted_numbered_list_util.get_indent) or any other fix-invented name, string, or module. The assertions ('\\n  - ', '\\n  2. ', selection-range offsets) describe the user-visible outcome (continuing/removing indented list items), so any correct implementation of the behavior would pass regardless of internal naming choices."
}
