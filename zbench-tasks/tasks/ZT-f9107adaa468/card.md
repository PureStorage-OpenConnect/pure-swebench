# ZT-f9107adaa468 -- streams: Do not archive vacant private streams.

- lang: py   issue: #33689   tier: B
- fix: https://github.com/zulip/zulip/commit/f9107adaa468a5a9b658ed0e139c743679cf7ae0
- f2p: zerver.tests.test_subs.StreamAdminTest.test_removing_last_user_from_private_stream
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior change (remove auto-archival of vacant private streams)",
  "reason": "Real, plausibly-assigned engineering task with a clear observable outcome: unsubscribing the last member of a private stream must no longer deactivate it. The hidden grader adds a behavioral test (test_removing_last_user_from_private_stream) that asserts stream.deactivated is False and no active subscriptions remain \u2014 deterministic, fail-before/pass-after, and not format-pinned. The removed test and decremented query-count assertions are standard Zulip conventions that follow directly from the behavior change, not incidental snapshot brittleness."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The new test exercises only pre-existing surfaces: the DELETE /json/users/me/subscriptions endpoint, its existing 'removed'/'not_removed' response fields, and existing ORM models (Stream.deactivated, Subscription, Recipient) to assert the user-visible behavioral change \u2014 a private stream is no longer auto-deactivated when its last subscriber leaves. The deleted test simply covered the old behavior. The query-count decrements use the pre-existing assert_database_query_count/attempt_unsubscribe_of_principal harness and follow mechanically from the fix: once vacancy-triggered deactivation is removed, the get_occupied_streams query has no consumer, and any reasonable implementation deletes it, yielding exactly one fewer query. No new names, fields, helpers, or internal structures are referenced, so a solver told only the behavioral requirement would pass on correctness, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the exact behavior to remove and names the code path (`new_vacant_private_streams`), and the expected-behavior evidence pins down the observable outcome: the channel stays active with no subscribers after the last unsubscribe, the response still reports the removal, default-stream removal no longer happens, and unsubscribe flows use one fewer database query. This is a determinate, checkable outcome."
}
