# ZT-a995510f0c98 -- worker: Flag messages processed by embedded bot.

- lang: py   issue: #28869   tier: B
- fix: https://github.com/zulip/zulip/commit/a995510f0c987e51a74c1e71e917ec2c370cbc79
- f2p: zerver.tests.test_service_bot_system.TestServiceBotEventTriggers.test_flag_messages_service_bots_has_processed
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix / behavior completion",
  "reason": "Real behavior change: embedded bot workers now flag processed messages as read, matching outgoing-webhook bots. The hidden test generalizes an existing outcome-based test across bot types and asserts the observable UserMessage 'read' flag state \u2014 deterministic, fail-before/pass-after, no snapshot or exact-string pinning."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test asserts a user-visible outcome through pre-existing interfaces: after a service bot's queue processor handles a message event, the message is marked as read via Zulip's existing message-flag system. It extends an existing test to all bot types using the test suite's existing @for_all_bot_types decorator. It never references the fix's new helper name (do_flag_service_bots_messages_as_processed), its signature, or module placement \u2014 any implementation that flags the message as read for embedded bots would pass. No new names or internal choices are pinned."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the problem, the rationale, and a concrete implementation sketch (stop filtering service bots, reorder get_service_bot_events, initial read flag based on planned events, mark read in the queue workers). The expected-behavior evidence confirms the chosen design: both service bot types must have messages flagged `read` once their queue processor handles them, which pins down the otherwise-open 'read vs. new flag' discussion in the issue. Together these give a determinate, checkable outcome."
}
