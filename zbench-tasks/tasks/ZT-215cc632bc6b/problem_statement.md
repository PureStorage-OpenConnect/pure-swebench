# Avoid fetching group membership for silently-mentioned user groups

## Background

Zulip's markdown pipeline supports mentioning user groups in message content with two syntaxes:

- `@*groupname*` — a regular (non-silent) group mention, which triggers notifications and therefore requires knowing the group's full membership (including members of subgroups, recursively).
- `@_*groupname*` — a silent group mention, which renders as a mention in the message body but does not notify anyone.

During message rendering, `zerver/lib/mention.py` scans the content for possible group mentions, and `MentionData` (backed by `MentionBackend`) resolves those names to groups and fetches each group's recursive membership from the database so downstream notification code can use it.

## Problem

The current code treats silent and non-silent group mentions identically for the purpose of data fetching: membership is fetched for every group mentioned in a message, even when a group is only mentioned silently. Since silent mentions never cause anyone to be notified, this membership data is never needed for them, and fetching it is wasted database work — which is especially costly because recursive (subgroup-aware) membership resolution is expensive, and messages can mention several groups at once. The goal is to reduce the database queries performed while processing group mentions by skipping membership resolution for groups that are only silently mentioned.

## Required behavior

1. **Mention scanning must distinguish silent from non-silent group mentions.** The content scanner must report, for each user-group name that appears in a group-mention syntax, whether the group was mentioned non-silently anywhere in the content or only silently. Non-group mentions (user mentions like `@**King Hamlet**`, wildcards like `@**all**`) and non-mention text (e.g. `smush@*steve*smush`, where the syntax is not a valid mention) must continue to be excluded, exactly as today.

2. **Non-silent takes precedence.** If the same group is mentioned both silently and non-silently in one message — in either order — it must be classified as non-silent. For example, in `@*help* the building is on fire!, folks should refer to @_*help*` and in `folks should refer to @_*help*, @*help* the building is on fire!`, the group `help` is non-silently mentioned.

3. **Membership is fetched only for non-silently mentioned groups.** When `MentionData` is constructed for content:
   - For a group with at least one non-silent mention, `MentionData.get_group_members(group_id)` must return the group's full recursive membership (all direct members plus members of subgroups, transitively) — unchanged from current behavior.
   - For a group mentioned only silently, `MentionData.get_group_members(group_id)` must return an empty set, and the implementation must not query the database for that group's membership.
   - Group identity resolution (mapping mentioned names to group objects/IDs) must still happen for silently-mentioned groups, since silent mentions still render and must resolve to a real group; only the membership fetch is skipped.

4. **Everything else about group-mention processing is unchanged**: rendering of both mention forms, handling of unknown group names, and behavior for messages with no group mentions must remain as they are today.

Both mention orders (silent-then-non-silent and non-silent-then-silent for the same group) must be handled correctly, as must messages mixing silent mentions of one group with non-silent mentions of another (e.g. `@*zulip_group*, @_*hamletcharacters*` must fetch membership for `zulip_group` but not for `hamletcharacters`).

## Interface requirements

- The function `possible_user_group_mentions(content)` in `zerver/lib/mention` changes its return type from a set of group names to a dict mapping each user-group name mentioned in the content to a mention-type string: `'silent'` for groups mentioned only with the silent syntax `@_*name*`, and `'non-silent'` for groups mentioned with the regular syntax `@*name*`.
- When the same group is mentioned both silently and non-silently in the same content, its dict entry must be `'non-silent'`, regardless of whether the silent or non-silent mention appears first.
- Group membership must not be fetched for groups that are only silently mentioned: for such groups, `MentionData.get_group_members(group_id)` returns an empty set, while groups with at least one non-silent mention return their full (recursive) membership as before.

## Callers

Audit callers of `possible_user_group_mentions` and any `MentionBackend`/`MentionData` code paths that consume its result, and update them for the new dict return type so that the silent/non-silent classification flows through to the membership-fetching decision.
