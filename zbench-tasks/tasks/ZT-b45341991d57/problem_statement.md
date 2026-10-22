## Resolving a topic that contains tens of thousands of messages can time out

### Observed behavior

In Zulip, marking a topic as resolved (or unresolving one) is an operation that acts on every message in the topic. When a topic has grown very large — on the order of 10,000s of messages — attempting to resolve it can exceed the request time limit and fail with a timeout. Users with such topics are effectively unable to resolve them: the resolve action never completes.

### Expected behavior

Resolving a topic should succeed regardless of how many messages the topic contains. The operation should complete without hitting the request timeout, even for topics with tens of thousands of messages.

### Reproduction

1. Create (or find) a topic containing tens of thousands of messages.
2. Attempt to mark the topic as resolved.
3. The request times out instead of completing.

### Notes

The failure stems from the current data model, in which a topic's resolved state is not stored as a single per-topic attribute but is instead derived from the messages themselves, so resolving must touch every message in the topic in one request. Possible directions include processing the messages in batches within the operation (essentially automating what one would otherwise do manually in chunks), or a larger restructuring where resolved state becomes a field on a per-topic database object so the operation no longer scales with message count. The immediate goal is to eliminate the timeout failure mode for large topics.
