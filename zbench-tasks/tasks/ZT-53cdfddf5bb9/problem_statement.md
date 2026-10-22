# Allow expanding a user-group pill into its members

## Background

In the Zulip web app, several "pill" input widgets accept user groups in addition to individual users — for example, the widgets for adding subscribers to a channel, adding members to a user group, and similar recipient/membership pickers. Since the permissions model was reworked to support groups containing other groups, selecting a group in one of these widgets adds the *group itself* (e.g., as a subgroup or as a group-based subscriber entry).

Before that rework, selecting a group meant "copy this group's current membership" — the individual users were what got added. That copy-membership workflow is still useful, and we want to offer it again alongside the new add-the-group-itself model: a user should be able to add a group pill and then, via a control on the pill itself, "explode" the pill into pills for the group's individual members.

## Current behavior

A user-group pill in these widgets is an atomic item: it displays the group name and a close/remove button. There is no way to convert the pill into pills for the group's members; the only options are to keep the group as a unit or remove it.

## Required behavior

1. **Expand control on group pills.** A user-group pill can render an additional control (a button on the pill, next to the existing close control) that expands the group. Activating it removes the group pill from the widget and inserts, in its place, pills for the group's direct membership: one user pill per member user, and one group pill per direct subgroup (subgroup pills should themselves be expandable in a context where expansion is enabled). Members that are already present as pills in the widget must not be duplicated.

2. **Per-context opt-in.** Whether the expand control appears is decided by the context that creates the pill widget, not globally. Widgets/flows that do not enable the feature must show group pills exactly as today, with no expand control. The pill data must record this decision (see interface requirements): pills created in contexts where expansion is not enabled carry an explicit `show_expand_button: false`, and the pill's rendered HTML shows the expand control only when the flag is true. This applies uniformly to all paths that create group pills, including pills created by selecting a typeahead suggestion and pills created programmatically (e.g., appending a group by name).

3. **Membership data model.** In the web client's data layer, a user group's member list is represented as a Set of user IDs (not an array). Any code that reads group membership for these pills — including the expansion logic and the typeahead logic that decides which suggestions to offer or which users a group pill already covers — must consume Set-based membership correctly.

4. **No behavior change for user pills.** Pills representing individual users are unaffected; only user-group pills gain the optional expand control.

## Interface requirements

- The exported user-group pill item type (the `UserGroupPill` data carried by pill widgets, containing `type: "user_group"`, `group_id`, and `group_name`) gains an optional boolean field `show_expand_button`, indicating whether the pill renders a control to expand the group into its members/subgroups. Pills created in contexts without expansion enabled must carry `show_expand_button: false`.

## Acceptance sketch

- In a widget with expansion enabled, adding the group "Admins" (members: three users) shows one pill with an expand button; clicking the button yields three user pills and no group pill. If one of those users already had a pill, only the missing two are added.
- In a widget without expansion enabled, adding "Admins" yields a group pill whose item data includes `show_expand_button: false` and whose rendering has no expand control.
