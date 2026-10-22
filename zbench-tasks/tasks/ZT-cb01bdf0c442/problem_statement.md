# Topic merge loses "followed" status on the destination topic

## Background

Zulip lets each user set a per-topic visibility policy on a channel topic. The possible policies are:

- **INHERIT** (no explicit policy; the channel-level setting applies)
- **MUTED**
- **UNMUTED**
- **FOLLOWED**

When a user moves all messages of a topic (propagate mode `change_all`) into a topic name that already exists in the same channel and already contains messages, the two topics are effectively **merged**. As part of a merge, the server must decide, for every user who has a visibility policy on either topic, what their policy on the resulting (destination) topic should be. Policies on the source topic name are cleared, since that topic no longer has messages.

## Bug

Today, the merge logic only reconciles the MUTED and UNMUTED policies. The FOLLOWED policy is not handled: when the source topic is merged into a destination topic that a user follows, the user's policy on the source topic (e.g. INHERIT, i.e. no policy at all) overwrites their FOLLOWED policy on the destination. Concretely:

1. A user follows topic A and has no policy on topic B (with auto-follow settings such that they followed A explicitly or automatically).
2. Someone moves all of topic B's messages into topic A, merging the topics.
3. The user is no longer following topic A — their FOLLOWED status was silently dropped, even though conversations they cared about are still happening in A.

Similarly, a FOLLOWED policy on the *source* topic is not correctly carried over to the destination in all combinations.

## Required behavior

When a topic move merges a source topic into an existing destination topic (same channel, destination already has messages, all messages moved), the server must compute each affected user's final visibility policy on the destination topic by *merging* the two policies rather than blindly copying the source policy over. The complete decision matrix is:

| Source topic policy | Destination topic policy | Final policy on destination |
|---|---|---|
| INHERIT | INHERIT | INHERIT |
| INHERIT | MUTED | INHERIT |
| INHERIT | UNMUTED | UNMUTED |
| INHERIT | FOLLOWED | FOLLOWED |
| MUTED | INHERIT | INHERIT |
| MUTED | MUTED | MUTED |
| MUTED | UNMUTED | UNMUTED |
| MUTED | FOLLOWED | FOLLOWED |
| UNMUTED | INHERIT | UNMUTED |
| UNMUTED | MUTED | UNMUTED |
| UNMUTED | UNMUTED | UNMUTED |
| UNMUTED | FOLLOWED | FOLLOWED |
| FOLLOWED | INHERIT | FOLLOWED |
| FOLLOWED | MUTED | FOLLOWED |
| FOLLOWED | UNMUTED | FOLLOWED |
| FOLLOWED | FOLLOWED | FOLLOWED |

The rows not involving FOLLOWED describe the existing, correct behavior and must be preserved unchanged. The rows involving FOLLOWED are the fix: **if either topic was FOLLOWED by the user, the merged topic must end up FOLLOWED** — FOLLOWED takes precedence over every other policy on either side.

Additionally, after the merge:

- Every affected user's policy on the **source** topic name must end up as INHERIT (i.e. no lingering explicit policy record for the now-empty source topic). This already happens for MUTED/UNMUTED and must also hold when the source topic was FOLLOWED.
- The usual client-facing updates for visibility-policy changes (the events/notifications that inform clients a user's per-topic policy changed) must reflect these outcomes, exactly as they do today for the MUTED/UNMUTED cases.

## Scope notes

- The relevant logic lives in the server-side message-move/topic-edit path that reconciles per-user topic visibility policies when a moved topic lands on a pre-existing topic with messages (the "merge" case).
- The fix must work regardless of how the FOLLOWED policy was originally established (manually or via automatic-follow settings).
- No API surface changes are required; this is a behavioral fix in how the final policy is computed during a merge.
