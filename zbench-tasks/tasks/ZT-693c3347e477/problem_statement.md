## Improve channel sorting priorities in `typeahead_helper.sort_streams`

### Current behavior

The channel/stream typeahead sorting logic in `typeahead_helper.sort_streams` (web client) does not prioritize channels in a way that matches how users think about channel importance. In particular, archived channels are not pushed to the bottom of typeahead suggestions, and the relative ordering of subscribed vs. unsubscribed channels, pinned vs. unpinned, active vs. inactive, and muted vs. unmuted channels does not follow a consistent priority scheme.

### Expected behavior

Channel prioritization in `typeahead_helper.sort_streams` should work as follows:

1. Archived channels should sort at the very bottom, below all un-archived channels.
2. Within both the archived group and the un-archived group, subscribed channels should rank above unsubscribed channels.

Among subscribed, un-archived channels, the order of importance should match the left sidebar's ordering:

1. Pinned channels first.
2. Then active channels before inactive channels.
3. Then unmuted channels before muted channels.

The existing recent-activity tiebreaker should be kept as-is for ordering channels that are equal on all of the above criteria.
