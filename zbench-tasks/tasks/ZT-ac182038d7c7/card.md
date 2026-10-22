# ZT-ac182038d7c7 -- message_report: Improve message report template.

- lang: py   issue: #36492   tier: B
- fix: https://github.com/zulip/zulip/commit/ac182038d7c703849c6851cff1d222ae5e2e9bf8
- f2p: zerver.tests.test_message_report.ReportMessageTest.test_channel_message_report, zerver.tests.test_message_report.ReportMessageTest.test_dm_report, zerver.tests.test_message_report.ReportMessageTest.test_gdm_report, zerver.tests.test_message_report.ReportMessageTest.test_personal_message_report_using_direct_message_group
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior-affecting improvement (notification template change)",
  "reason": "The deliverable of this task IS the new moderation-request message format (reworded headers, quote block with report type, spoiler linking to the original message, sorted recipient mentions), so the hidden test asserting the composed message content grades exactly the observable behavior the fix changes \u2014 not incidental formatting. The assertions are deterministic: mentions, links, and fences are built from the same library helpers (silent_mention_syntax_for_user, pm_message_url, get_unused_fence), and the code change even sorts the group-DM recipient list, removing ordering nondeterminism. It fails before and passes after the change, and 'improve formatting of moderation request messages' per an issue is a plausible real engineering assignment; any wording-spec thinness in the issue is handled by later stages."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The report header for a reported channel message must read '{reporting_user} reported a message sent by {reported_user}.' using silent mention syntax for both users, with no message link in the header.",
    "The report header for a reported 1:1 direct message must read '{reporting_user} reported a direct message sent by {reported_user}.' ('direct message' replaces the old 'DM' wording).",
    "The report header for a reported group direct message must read '{reporting_user} reported a direct message sent by {reported_user} to {recipients}.' where {recipients} lists silent mentions of all group members sorted alphabetically, comma-separated, with ', and ' before the final member.",
    "Immediately after the header, the report reason and notes must appear as a single Markdown quote block whose content is '**{report_type}**. {description}' (bold report type, a period and space, then the reporter's description), replacing the old '- Reason:'/'- Notes:' bullet format.",
    "After the quote block (separated by a blank line), the reported message content must appear inside a spoiler fence built with an unused fence for the quoted content.",
    "For a reported channel message, the spoiler header must be '**Original message at {channel_message_link}**' where {channel_message_link} is the existing channel/topic/message link syntax (get_message_link_syntax) for the reported message.",
    "For a reported direct message (1:1 or group), the spoiler header must be '**[Original message]({url})**' where {url} is the near-message narrow URL to that direct-message conversation produced by the existing pm_message_url helper (i.e. the standard DM permalink for the reported message id and its recipients)."
  ],
  "reason": "The test exercises the feature through pre-existing surfaces (the report-message endpoint, get_last_message) and computes expected links with helpers that already exist at the base commit (pm_message_url, get_display_recipient, get_message_link_syntax, get_unused_fence). Everything new it binds to is the exact user-facing notification template \u2014 header wording, quote-block format, spoiler titles, recipient ordering \u2014 which a ticket/design spec would legitimately dictate verbatim. No private helper names, mock targets, or internal structures are referenced, so with the listed message-format requirements in the brief the test grades correctness rather than name-guessing."
}

## screen: f2p_llm_fallback
{
  "tests": [
    "zerver.tests.test_message_report.ReportMessageTest.test_channel_message_report",
    "zerver.tests.test_message_report.ReportMessageTest.test_dm_report",
    "zerver.tests.test_message_report.ReportMessageTest.test_personal_message_report_using_direct_message_group",
    "zerver.tests.test_message_report.ReportMessageTest.test_gdm_report"
  ],
  "reason": "The diff matches zulip/zulip commit ac182038 ('message_report: Improve message report template', #36492). Its test hunks (old lines ~100, ~201, ~253, ~300-330) land inside four methods of ReportMessageTest per the pre-commit file: test_channel_message_report, test_dm_report, test_personal_message_report_using_direct_message_group, and test_gdm_report. The other hunks only modify module imports and add no new test methods."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives the motivation and the target format for channel-message reports, and the expected-behavior evidence pins down the exact output for all three cases (channel message, 1:1 DM, group DM), including the new header wording, merged reason/description quote block, blank line before the spoiler, the new spoiler headers with message links, alphabetical group-DM recipient ordering, and the helpers to use (get_message_link_syntax, pm_message_url, get_unused_fence). This is enough to state a determinate, checkable outcome."
}
