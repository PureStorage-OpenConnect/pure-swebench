# ZT-ffa1675da380 -- reactions: Live-update vote text in pills on user rename.

- lang: web   issue: #38595   tier: B
- fix: https://github.com/zulip/zulip/commit/ffa1675da380ab1fdfbc183ed1f2dd97098fde3a
- f2p: web/tests/reactions.test.cjs
- p2p: web/tests/user_events.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix (live-update UI behavior)",
  "reason": "Real engineering task: reaction pill vote text failed to live-update on user rename. The hidden test grades observable behavior deterministically \u2014 it verifies update_vote_text_on_message is invoked exactly for messages containing the renamed user's reactions and not otherwise, using message IDs rather than pinned output strings or HTML snapshots. Fail-before/pass-after is clear since the function didn't exist and the event handler didn't trigger re-rendering."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The `reactions` module gains a public function `update_user_full_name(user_id: number)`, invoked from the realm-user update event path when a user's full name changes, so that reaction vote text (which can contain display names) stays current.",
    "`update_user_full_name(user_id)` must enumerate rendered messages via the existing `message_lists.all_rendered_message_lists()` API and, for each message whose reactions include `user_id`, trigger the module's existing per-message vote-text re-render routine `update_vote_text_on_message(message)` exactly once per affected message.",
    "For a `user_id` that appears in no reactions on any rendered message, `update_user_full_name` must perform no vote-text updates."
  ],
  "reason": "The only new name the test binds is `reactions.update_user_full_name(user_id)`, a module-level function intended as the public entry point for the name-change event path \u2014 exactly the kind of API surface a ticket would dictate (it mirrors the pre-existing `message_live_update.update_user_full_name` convention). The test's other touchpoints are pre-existing interfaces at the base commit: `message_lists.all_rendered_message_lists()` is an existing API, and `update_vote_text_on_message` already exists in reactions.ts with rewire support and its own test before this change, so stubbing it observes behavior through an established seam rather than an internal the fix invents. Given a brief stating the contract above, the test grades correctness (affected messages re-rendered, unaffected users no-op), not name-guessing. The one mild bind \u2014 requiring the update to flow through `update_vote_text_on_message` per message \u2014 is the module's canonical pre-existing re-render path, so a spec could legitimately pin it."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user-visible defect (pills don't live-update names while tooltips do), and the evidence plus interface requirements pin down the exact public function name, its input, the enumeration API to use, the per-message re-render routine to invoke, the once-per-affected-message semantics, and the no-op case for uninvolved users. Two engineers working independently from this brief would produce compatible implementations."
}
