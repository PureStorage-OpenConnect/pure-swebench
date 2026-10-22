# ZT-52b83f7b5883 -- topic_list: Filter topics by resolved state in "more topics" view.

- lang: web   issue: #24200   tier: B
- fix: https://github.com/zulip/zulip/commit/52b83f7b58830e39d29f858f6f54896cacba5683
- f2p: web/tests/pill_typeahead.test.cjs, web/tests/stream_list.test.cjs, web/tests/stream_topic_history.test.cjs, web/tests/topic_list_data.test.cjs
- p2p: web/tests/topic_list.test.cjs, web/tests/typeahead_helper.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "new feature",
  "reason": "Real feature work (filtering topics by resolved/unresolved state in the left sidebar) with a genuine issue behind it. The hidden tests grade observable behavior deterministically: filter_topics_by_search_term returns the correct topic subset for 'is:resolved'/'-is:resolved', stream_has_locally_available_resolved_topics flips false\u2192true when a resolved topic is added, and render_topic_state produces the expected item. These assert small, stable return values rather than pinned long strings or HTML/JSON snapshots, so they fail-before/pass-after on the actual behavior change and are not brittle."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "Module `web/src/typeahead_helper` exports a new function `render_topic_state(state: string)` that renders a typeahead list item for a topic-state filter option by delegating to the module's existing exported `render_typeahead_item` helper, called with an args object whose `primary` field is the state string (e.g. \"Resolved\"), and returns that helper's result verbatim.",
    "Module `web/src/topic_list_data`'s existing exported `filter_topics_by_search_term(topic_names, search_term)` gains a third parameter `topics_state: string`. Sentinel semantics asserted by the test: the exact string \"is: resolved\" (with a space after the colon) filters to only resolved topics (names beginning with the \"\u2714 \" resolved-topic marker); the exact string \"-is: resolved\" filters to only unresolved topics; ordering of surviving topics is preserved.",
    "Module `web/src/stream_topic_history` exports a new function `stream_has_locally_available_resolved_topics(stream_id: number): boolean` returning false for a stream with no locally cached topic history, and true once any locally known topic in that stream is resolved (i.e. a message was added with a \"\u2714 \"-prefixed topic name).",
    "Module `web/src/topic_list` exports a function `setup_topic_search_typeahead()` (as a mutable/stub-able module property) that is invoked from `stream_list`'s topic-zoom flow; the test only requires that it exists under this name and is called during zoom-in so it can be stubbed to a noop."
  ],
  "reason": "All four bindings are to new exported, module-level names with clear behavioral semantics that a ticket could legitimately dictate: two new public functions with defined boolean/rendering behavior, a new parameter with user-facing search-syntax sentinels (\"is: resolved\" / \"-is: resolved\"), and a setup hook whose existence and call-site a spec can state. The one implementation-flavored assertion \u2014 that render_topic_state delegates to render_typeahead_item with {primary: state} \u2014 targets a pre-existing public helper that all sibling render_* functions in typeahead_helper already delegate to (and which this test file already mocks for them), so specifying that delegation in the brief matches the established module pattern rather than forcing a guess at a private invention. No private helpers, internal field names, or log wording are asserted. Given these contract items in the brief, the tests grade correctness, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue gives a concrete UX spec (typeahead with Resolved/Unresolved suggestions, pills, gating on presence of resolved topics), and the evidence pins down the exact observable semantics: the sentinel state strings \"is: resolved\"/\"-is: resolved\", filtering by the \"\u2714 \" prefix with order preserved, the per-stream resolved-topic availability check, the render_topic_state delegation contract, and that setup_topic_search_typeahead is wired into stream_list's zoom-in flow. Together these define a determinate, checkable outcome."
}
