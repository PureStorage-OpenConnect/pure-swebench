# Short-circuit `check_can_access_user` for self-access and spectators

## Background

Zulip supports realms where guest users have *limited user access* (controlled by the realm's `can_access_all_users_group` setting). The helper `check_can_access_user(target_user, user_profile)` in `zerver/lib/users.py` decides whether `user_profile` is allowed to access `target_user`, and is called from hot code paths: sending direct messages, generating push-notification payloads, subscription add/remove flows, and computing recipients for user-creation events.

## Current behavior

`check_can_access_user` begins by evaluating the realm-level access policy before looking at who is being checked against whom. Concretely:

- When a user checks access **to themself** (`target_user` is the same user as `user_profile`), the function still performs policy lookups: for an ordinary guest this costs one database query (resolving the realm's `can_access_all_users_group` setting), and for a guest with limited user access it costs two queries, even though the answer is trivially "yes".
- Because these lookups can be served from memcached, the wasted work shows up as extra database queries and/or extra cache fetches in every calling code path where the accessing user and the target user are the same person (e.g. a user sending a DM to themself, or a push-notification payload being built where the sender is the recipient).

This is a pure performance problem; the boolean results returned today are correct.

## Required behavior

Reorder/restructure `check_can_access_user` so that the trivially-true cases are decided **before any database query or cache lookup is issued**:

1. **Self-access:** If `user_profile` is the same user as `target_user`, return `True` immediately. This must perform **zero database queries and zero cache fetches**, and must hold both for ordinary guests and for guests with limited user access — the query cost of a self-check must be identical (zero) in both cases.
2. **Spectators:** If `user_profile` is `None` (an unauthenticated spectator viewing a web-public realm), return `True` immediately. Spectators already have a very restricted view of user data, so no per-user access check is needed.

These short-circuits must come before the evaluation of the realm's `can_access_all_users_group` policy (and before any related user-group / setting lookups), so that callers see the savings automatically.

### Observable effects in calling code paths

Because the function no longer touches the database or cache when the accessing user *is* the target user, each code path that invokes it in that situation must get cheaper by exactly the queries/cache fetches it previously spent there. In particular:

- Building a push-notification payload for a channel message where the notified user is the message's sender must no longer incur the user-group query previously spent in the `check_can_access_user` code path (one fewer database query for that flow).
- A guest with limited user access sending a personal message to themself must incur one fewer database query than before.
- Subscription add/remove flows that check access against the acting user themself must each drop one memcached fetch.

## Constraints

- Do not change the function's results for any other input: guests with limited user access must still be denied access to users they cannot see, and all existing access rules for non-self targets must behave exactly as before.
- The function's signature and call sites should remain compatible; this is an internal reordering/optimization, not an API change.
- No new caching layer is required — the fix is to avoid the lookups entirely in the two trivial cases, not to cache their results.

## Acceptance criteria

- `check_can_access_user(polonius, polonius)` returns `True` with zero database queries, both before and after the realm is configured to give guests limited user access.
- `check_can_access_user(some_user, None)` returns `True`.
- End-to-end flows (self-DM by a limited guest, push notification where sender == recipient, subscribe/unsubscribe flows checking the acting user) each perform one fewer database query or cache fetch than they currently do, with no behavioral change in their responses or emitted events.
