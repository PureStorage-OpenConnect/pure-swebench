# Apply automatic follow/unmute visibility policies when messages are moved to a topic they now "initiate"

## Background

Zulip users have two personal settings that automatically change a topic's visibility policy for them:

- `automatically_follow_topics_policy` — when set to the "on topic initiation" option (`UserProfile.AUTOMATICALLY_CHANGE_VISIBILITY_POLICY_ON_INITIATION`), a topic is automatically set to FOLLOWED (`UserTopic.VisibilityPolicy.FOLLOWED`) for a user when they start that topic.
- `automatically_unmute_topics_in_muted_streams_policy` — with the same "on topic initiation" option, a topic in a stream the user has muted is automatically set to UNMUTED (`UserTopic.VisibilityPolicy.UNMUTED`) for them when they start that topic.

Today these policies are only applied on the message-send path: a user "initiates" a topic by sending its first message. They are **not** applied when messages are moved (the message-edit endpoint, `PATCH /json/messages/{message_id}`, with a new `topic` and/or `stream_id`, including the propagate modes that move multiple messages).

This is a gap: a common moderation flow is to take a message someone posted in the wrong place and move it out to become the first message of a new topic. Conceptually that user initiated the new topic, and their notification configuration should end up the same as if they had actually started it — but currently no visibility policy is set for them.

## Required behavior

When messages are moved to a different topic and/or stream, the server must additionally apply the automatic follow and automatic unmute policies to the **sender of the message that becomes the first message of the destination topic**, exactly as if that sender had initiated the topic by sending that message.

Concretely, after a move completes:

1. Determine whether one of the *moved* messages is now the first (oldest) message of the destination topic. This is the case when:
   - the destination topic had no messages before the move, or
   - the oldest moved message predates every message that already existed in the destination topic.
   If the destination topic already had an older message than any moved message, no policy is applied to anyone as part of this move.
2. If a moved message is now the topic's first message, let *S* be its sender. Then:
   - If *S*'s `automatically_follow_topics_policy` is the "on initiation" value, set *S*'s visibility policy for the destination (stream, topic) to FOLLOWED.
   - Otherwise, if *S*'s `automatically_unmute_topics_in_muted_streams_policy` is the "on initiation" value **and** *S* has the destination stream muted (their `Subscription.is_muted` is true), set *S*'s visibility policy for the destination (stream, topic) to UNMUTED.
3. **Access check:** only apply a policy for *S* if *S* can actually access the moved message in its new location. In particular, if the destination is a private stream with protected history (`invite_only=True`, `history_public_to_subscribers=False`) and *S* is not subscribed to it, do **not** set any visibility policy for *S*.

Notes and edge cases:

- The rule is evaluated per move operation. Successive moves into the same topic can each trigger the policy: e.g., topic T is empty; moving message M1 (sender A) into T follows T for A; later moving an even older message M2 (sender B) into T makes M2 the new first message, so T is then also followed for B (whose policy is set accordingly). Moving a message that lands *after* the topic's existing first message must not change its sender's visibility policy.
- Policies apply based on the *sender* of the moved message, not the user performing the move. The mover may be a different user (e.g., a moderator); their own policies for this situation are governed by the same rule — they are only affected if a message *they sent* becomes the first message of the destination.
- Message ordering ("first"/"oldest") follows the same ordering used elsewhere for topic history (message ID order).
- Visibility-policy changes made this way must go through the normal machinery for setting a user's topic visibility policy (persisting a `UserTopic` row and notifying that user's clients via the usual `user_topic` events), identical in effect to the policy being applied on message send. The existing precedence rules apply (e.g., FOLLOWED is checked before UNMUTED; don't overwrite an existing FOLLOWED policy with UNMUTED).
- Behavior of the send path is unchanged; this only adds handling to the move-message path.

## Verification sketch

With four subscribed users who all have `automatically_follow_topics_policy` set to the "on initiation" option, each sending one message (in order) to topic "original" in a stream:

- Only the sender of the first message in "original" has it FOLLOWED.
- Moving the third message to empty topic "post-move" (same stream) causes its sender to have "post-move" FOLLOWED.
- Then moving the fourth message into "post-move" does **not** follow it for that sender (their message is newer than the topic's existing first message).
- Then moving the second message into "post-move" **does** follow it for that sender (their message is now the oldest there).
- Repeating the flow into a topic in a protected-history private stream: a sender who is not subscribed to the private stream does not get the topic followed; a subscribed sender does.

The same scenarios with `automatically_unmute_topics_in_muted_streams_policy` set to the "on initiation" option and the stream muted for each user must produce the analogous UNMUTED visibility policies.

## Interface requirements

- The "first (oldest) message of the destination topic" test in step 1 is evaluated from the **sender's own message visibility**, not globally. Preexisting messages in the destination topic that the sender *S* cannot access (for example, messages sent to a protected-history private stream before *S* subscribed) are ignored when deciding whether a moved message is the topic's first message. Consequently, if every older message already in the destination topic is invisible to *S*, then *S*'s moved message counts as that topic's first message for *S*, and the follow/unmute policy applies (subject to the access check in step 3).
