# Filter topics by resolved/unresolved state in the "more topics" view

## Background

In the Zulip web app's left sidebar, clicking "more topics" under a channel zooms the sidebar into a full topic list for that channel, with a search input that filters topics by a plain-text search term. Zulip marks a topic as *resolved* by prefixing its name with the resolved-topic marker `"✔ "` (check mark followed by a space).

Currently, the "more topics" search input only does substring-style text matching. There is no way to restrict the zoomed topic list to only resolved or only unresolved topics. The global search bar supports `is:resolved`, but that runs a full message search and is not equivalent to filtering the sidebar topic list.

## Required behavior

Add a resolved/unresolved filter to the "more topics" topic search, implemented as a typeahead that inserts a filter pill into the search input.

### Typeahead and pill UX

- When the user zooms into the "more topics" view for a channel, a typeahead must be set up on the topic search input.
- If the channel has **no resolved topics among its locally cached topic history**, behavior stays exactly as today: plain text filtering, no topic-state typeahead suggestions.
- Otherwise, the typeahead offers two suggestions: **"Resolved topics"** and **"Unresolved topics"**. Each suggestion row is rendered through the standard typeahead item renderer, with the state string (e.g. "Resolved") as the item's primary text.
- Selecting a suggestion inserts a pill into the search box representing the filter (resolved → the `is: resolved` state; unresolved → the negated `-is: resolved` state). At most one topic-state pill applies at a time.
- The typeahead closes when a pill has been selected, or when the user's input no longer matches either suggestion (matching should be tolerant of the same operator/keyword variants accepted by the main search typeahead).
- With a pill active, any remaining free text in the input still acts as a plain text search term, combined with the state filter.

### Filtering semantics

The topic-list filtering logic must accept a topic-state value alongside the text search term and apply both:

- State `"is: resolved"` (exact string, with a space after the colon): keep only topics whose names begin with the `"✔ "` resolved marker.
- State `"-is: resolved"` (exact string): keep only topics whose names do **not** begin with the resolved marker.
- Any other state value (including empty/none): no state-based filtering; text-term filtering behaves as before.
- The relative order of the topics that survive filtering must be preserved from the input list.
- An empty text search term with a state filter applied must still filter by state (e.g. topics `["topic 1", "✔ resolved topic", "topic 2"]` with state `"is: resolved"` yields exactly `["✔ resolved topic"]`; with state `"-is: resolved"` yields exactly `["topic 1", "topic 2"]`).

### Detecting locally available resolved topics

The client-side per-channel topic history module must be able to report whether a channel has any resolved topic in its locally cached history:

- For a channel with no locally cached topic history, the answer is `false`.
- After a message is recorded for that channel under a topic whose name starts with `"✔ "`, the answer for that channel becomes `true`.

This check gates whether the typeahead offers the Resolved/Unresolved suggestions (see UX above).

## Interface requirements

- Module `web/src/typeahead_helper` exports a new function `render_topic_state(state: string)` that renders a typeahead list item for a topic-state filter option by delegating to the module's existing exported `render_typeahead_item` helper, called with an args object whose `primary` field is the state string (e.g. "Resolved"), and returns that helper's result verbatim. `render_topic_state` must be exported as a mutable, stub-able binding (the `export let name = …` rewire idiom used for testable module functions), so a test can rewire it — the same stub-ability required for `setup_topic_search_typeahead` below.
- Module `web/src/topic_list_data`'s existing exported `filter_topics_by_search_term(topic_names, search_term)` gains a third parameter `topics_state: string`. The exact string `"is: resolved"` (with a space after the colon) filters to only resolved topics (names beginning with the `"✔ "` resolved-topic marker); the exact string `"-is: resolved"` filters to only unresolved topics; the ordering of surviving topics is preserved.
- Module `web/src/stream_topic_history` exports a new function `stream_has_locally_available_resolved_topics(stream_id: number): boolean` returning `false` for a stream with no locally cached topic history, and `true` once any locally known topic in that stream is resolved (i.e. a message was added with a `"✔ "`-prefixed topic name).
- Module `web/src/topic_list` exports a function `setup_topic_search_typeahead()` as a mutable (stub-able) module property. It must be invoked from `web/src/stream_list`'s topic-zoom (zoom-in) flow to install the typeahead on the topic search input when the user enters the "more topics" view.
