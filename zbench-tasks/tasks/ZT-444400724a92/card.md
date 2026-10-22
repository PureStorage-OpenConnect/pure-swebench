# ZT-444400724a92 -- message_report: Add reported message date sent to report template.

- lang: py   issue: #36997   tier: B
- fix: https://github.com/zulip/zulip/commit/444400724a92a74883dff89d62985ec1b33615db
- f2p: zerver.tests.test_message_report.ReportMessageTest.test_dm_report, zerver.tests.test_message_report.ReportMessageTest.test_dm_to_oneself, zerver.tests.test_message_report.ReportMessageTest.test_gdm_report_with_more_than_3_recipients, zerver.tests.test_message_report.ReportMessageTest.test_personal_message_report_using_direct_message_group, zerver.tests.test_message_report.ReportMessageTest.test_reporting_own_dm_to_other
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real, assignable feature work: include the reported message's send time in the moderation report header. The observable outcome is the content of the report message delivered to moderators, and the hidden test grades exactly that. Determinism concerns are handled: the test freezes time with time_machine (tick=False) and builds the expected timestamp via the same datetime_to_global_time helper the product code uses, so there is no wall-clock or formatting flakiness. While the test does compare full report strings, that pattern pre-exists this change and the string IS the behavior under test (a user-visible message body), not incidental serialization \u2014 a fail-before/pass-after signal is clean because the pre-change code omits the timestamp entirely."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "A public helper function `datetime_to_global_time(date_sent)` must exist in the module `zerver.lib.timestamp`, taking a datetime and returning the string rendering of that timestamp in Zulip's global-time markdown syntax (e.g. `<time:...>`), for use by any code that embeds message timestamps in message content.",
    "The moderation-report message header for a reported channel message must read exactly: '{reporting_user_mention} reported a message sent by {reported_user_mention} at {time}.', where {time} is the reported message's date_sent rendered via datetime_to_global_time.",
    "The report header for a reported 1:1 direct message (reporter is not the sender) must read exactly: '{reporting_user_mention} reported a direct message sent by {reported_user_mention} at {time}.'",
    "The report header when a user reports their own direct message must read exactly: '{reporting_user_mention} reported a direct message sent by {reported_user_mention} to {recipient_mention} at {time}.'",
    "The report header for a reported group direct message must read exactly: '{reporting_user_mention} reported a direct message sent by {reported_user_mention} to {recipient_users} and {last_recipient_user} at {time}.' (recipient list formatting unchanged from existing behavior, with the ' at {time}' suffix appended before the period)."
  ],
  "reason": "The test binds only to new contract surface a brief could dictate: exact user-facing report-header wording (message copy) and a new shared timestamp helper `datetime_to_global_time` in `zerver.lib.timestamp`, a public-library function whose name/location a ticket would reasonably pin. The test computes expected timestamps through that same helper, so no undocumented output format must be guessed beyond the helper's existence and use. No private internals, mock targets, or implementation layout are asserted, so with these requirements in the brief the test grades correctness rather than name-guessing."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_message_report.ReportMessageTest.test_dm_report",
    "zerver.tests.test_message_report.ReportMessageTest.test_dm_to_oneself",
    "zerver.tests.test_message_report.ReportMessageTest.test_reporting_own_dm_to_other",
    "zerver.tests.test_message_report.ReportMessageTest.test_personal_message_report_using_direct_message_group",
    "zerver.tests.test_message_report.ReportMessageTest.test_gdm_report_with_more_than_3_recipients"
  ],
  "reason": "Five test methods are directly modified, each gaining a @time_machine.travel(MOCKED_DATE_SENT, tick=False) decorator to freeze the message send time. The other hunks touch setUp and shared assertion helpers (the report-message content checks now include the formatted date_sent), which are not test methods themselves; their effects are exercised through the class's tests, and running the ReportMessageTest class via these targets covers the changed behavior."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue plus the expected-behavior evidence pin down a determinate, checkable outcome: the exact header strings for all four report-notice variants and a reusable zerver.lib.timestamp.datetime_to_global_time helper rendering date_sent in global-time markdown. The issue's separate suggestion to rename the moderation topic is not reflected in the evidence or interface requirements, so the brief explicitly leaves the topic unchanged to keep independent implementations compatible."
}
