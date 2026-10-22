# ZT-be5c6f10918d -- message_store: Conditionally update message's raw_content.

- lang: web   issue: #37908   tier: B
- fix: https://github.com/zulip/zulip/commit/be5c6f10918df52787ed842b7b97f257e644fbb8
- f2p: web/tests/message_events.test.cjs, web/tests/message_store.test.cjs
- p2p: web/tests/echo.test.cjs, web/tests/message_edit.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real bug fix with observable behavior change: raw_content caching is now conditional on channel subscription. The hidden test exercises maybe_update_raw_content directly with three concrete cases (subscribed channel caches, unsubscribed channel skips, stale cached value is cleared) and asserts field values, not snapshots or exact rendered output. It deterministically fails before the fix (the function doesn't exist / raw_content would be set unconditionally) and passes after. This is a plausible assigned engineering task in the real-time sync area."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The `message_store` module gains an exported function `maybe_update_raw_content(message, raw_content)`: the single entry point callers must use when caching a message's raw (markdown) content locally, replacing direct assignment to `message.raw_content`.",
    "Semantics of `maybe_update_raw_content`: for a stream message in a channel the current user IS subscribed to, it sets `message.raw_content` to the provided value.",
    "Semantics of `maybe_update_raw_content` for unsafe caching: for a stream message in a channel the current user is NOT subscribed to (where content-update events will not be received), it must NOT store the provided value and must set `message.raw_content` to `undefined`, clearing any previously cached raw content so a stale version cannot be reused."
  ],
  "reason": "The test binds to one new name: `message_store.maybe_update_raw_content`, an exported module-level function that the fix uses as the shared caching gate across four caller modules (compose_reply, echo, message_edit, message_events). This is exactly the kind of module-boundary API a ticket would dictate ('add a helper in message_store that all raw_content caching goes through, with these subscribe/unsubscribe semantics'), and the test's assertions \u2014 set when subscribed, leave undefined when not, reset stale cached content \u2014 are the product behavior itself, including the `undefined` sentinel. The test's other dependencies are pre-existing surfaces: `stream_data.add_sub_for_tests` and `stream_data.is_subscribed` exist at the base commit, and the `message_events.test.cjs` fixture change (Denmark becomes subscribed) merely updates an existing test's setup to remain consistent with the new behavior. No private internals, mock targets, or internal data-structure choices are pinned; with the three contract items in the brief, the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue explains the stale-cache race clearly, the expected-behavior evidence pins down the exact observable semantics (store when subscribed, clear to undefined when not, including previously-cached values), and the interface requirements name the exact exported function. Together they define a determinate, checkable outcome."
}
