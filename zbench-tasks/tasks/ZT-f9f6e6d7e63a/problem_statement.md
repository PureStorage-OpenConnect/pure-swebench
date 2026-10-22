# Optimize database queries for resolving user-group mentions in a message

## Context

When Zulip renders a message, the Markdown pipeline builds a `MentionData` object (in `zerver/lib/mention.py`) that resolves everything mentioned in the message content: users, wildcards, and user groups (`@*group-name*` syntax). For each mentioned group, the system must know the group's full **transitive** membership — i.e., direct members plus members of all subgroups, recursively — because group mentions notify every user who is a member of the group directly or via nested subgroups.

## Current behavior (the problem)

Group-mention resolution currently performs database work **per mentioned group**: after looking up the mentioned group names, the code loops over the groups and issues additional queries for each one to compute its recursive membership. As a result, the number of database queries grows linearly with the number of distinct groups mentioned in a single message. A message mentioning ~10 groups causes ~40 queries during `MentionData` construction. This is a scalability problem for messages that mention many groups.

## Required behavior

Constructing `MentionData` for message content that mentions user groups must issue a **constant** number of database queries, independent of how many groups are mentioned — the per-group query fan-out must be eliminated.

Concretely, the group-mention resolution path must use exactly **2 queries**:

1. One query that looks up the mentioned `NamedUserGroup` rows by name (for the message's realm).
2. One bulk query that resolves the recursive (transitive) active membership of **all** mentioned groups at once.

A recursive SQL construct (e.g., a `WITH RECURSIVE` common table expression over the group/subgroup membership tables) is the expected approach for collapsing the per-group recursive-membership queries into a single bulk query. Postgres is the only supported database, so Postgres-specific SQL features are acceptable, consistent with how single-group recursive membership is already computed elsewhere in `zerver/lib/user_groups.py`.

## Correctness constraints

The optimization must not change the semantics of group-mention resolution:

- **Membership semantics:** For each mentioned group, the resolved member set must equal the group's transitive closure of membership — active direct memberships plus, recursively, active memberships of all subgroups. Only rows representing active membership count (respect the same activity/`is_active` filtering the existing single-group recursive-membership logic uses).
- **Deactivated groups:** Mentions of deactivated groups must not resolve as group mentions; deactivated groups must be excluded from membership resolution just as they are today.
- **Per-group attribution preserved:** `MentionData` must still be able to answer, per group ID, which users are members of that specific group (e.g., its existing accessor for group members must return the correct, distinct set of user IDs for each mentioned group individually — the bulk query must not merge all groups' members into one undifferentiated pool).
- **Silent mentions and multiple mentions of the same group** must continue to behave as before.
- **No behavior change for messages without group mentions:** if the content mentions no groups, no group-related queries should be issued.

## Interface requirements

- Constructing `MentionData` (given a mention backend, message content, and message sender) for content that mentions user groups must issue a constant number of database queries regardless of how many groups are mentioned — no per-group query fan-out.
- That constant must be exactly **2 queries** for the group-mention resolution path: one query to look up the mentioned `NamedUserGroup` rows by name, and one bulk query that resolves the recursive (transitive) active membership of all mentioned non-deactivated groups at once.

## Acceptance criteria

- A message mentioning N distinct user groups (for any N ≥ 1, including groups with overlapping and nested memberships) triggers exactly 2 database queries for group-mention resolution during `MentionData` construction, where the pre-change behavior issued a number of queries growing with N.
- The resolved membership for each mentioned group is identical (same user IDs per group) to what the pre-change per-group recursive resolution produced.
- All existing mention behavior (user mentions, wildcard mentions, notification fan-out driven by group membership) is unchanged.
