# Replace the "Enable message edit history" checkbox with a three-option message edit history visibility policy

## Background / current behavior

Zulip organizations currently have a boolean realm setting, `allow_edit_history`, exposed to clients as `realm_allow_edit_history` in the register/event payloads. It is presented in the web app under **Settings > Organization permissions** as a checkbox labeled "Enable message edit history". When enabled, users can view the full history of a message — both content edits and moves (channel/topic changes). When disabled, no history is viewable at all.

This is too coarse. Some organizations want members to be able to see that (and where) messages were *moved*, without exposing the history of message *content edits*. An intermediate option also makes `near` message links behave better than when history is fully disabled.

## Required behavior

Replace the boolean setting with an integer-enum realm setting named `message_edit_history_visibility_policy` with three policy values:

1. **Always** — full message edit history (content edits and moves) is visible. This is the default, and is the behavior organizations previously got with the checkbox enabled.
2. **Moves only** — users can view the history of a message's moves (channel and topic changes), but the history of content edits is not exposed anywhere (neither in the UI nor via the API).
3. **Never** — no message edit history is visible at all, matching the old checkbox-disabled behavior. In this state, the edit-history UI (e.g. "View edit history" actions and the edit-history modal) must be suppressed, and clients should not perform client-side `edit_history` bookkeeping on messages.

Server-side work this implies:

- Add the new realm field and remove/replace the boolean `allow_edit_history`, including a database migration that maps existing values (`true` → Always, `false` → Never).
- Expose the new setting as `realm_message_edit_history_visibility_policy` in the data sent to clients, replacing `realm_allow_edit_history`, and support changing it through the realm-update API with the usual realm `update` events so connected clients stay in sync. Reject values outside the defined enum.
- Enforce the policy when serving message edit history: under "Moves only", history responses must include only move-related entries (stream/topic changes) and must not leak prior message content from edits; under "Never", history must not be available.

Web-app work this implies:

- In **Settings > Organization permissions**, replace the "Enable message edit history" checkbox with a dropdown labeled along the lines of "Show message edit history?" offering the three options (Always / Moves only / Never). It must participate in the standard save/discard flow for organization settings: changing the dropdown enables the save/discard widget, and discarding changes restores the dropdown's value to the current realm policy code.
- Gate all edit-history UI on the new policy: with "Never", hide edit-history affordances entirely and skip maintaining `edit_history` data on messages client-side; with "Always", show full history; with "Moves only", show only move history.
- Update user-facing documentation (help center pages that describe disabling message edit history and restricting moderation/editing) to describe the new three-option setting.

Exact user-facing strings may be polished, but the three options must correspond to the semantics above with **Always** as the default.

## Interface requirements

- The realm object must gain an integer-enum setting `realm_message_edit_history_visibility_policy`, replacing the boolean `realm_allow_edit_history`.
- The frontend module `settings_config` must export `message_edit_history_visibility_policy_values`, an object with (at least) keys `always` and `never`, each entry having a numeric `code` property holding the API enum value for that policy. All code that needs a policy's numeric value must reference it through this object rather than hard-coding numbers.
- Semantics: the policy code for `never` means message edit history is not visible (edit-history UI suppressed, no client-side `edit_history` bookkeeping); the code for `always` means full edit history is visible.
- The organization-settings UI must expose the policy as an input (a `<select>`) with DOM id `#id_realm_message_edit_history_visibility_policy`, following the existing `#id_realm_<setting_name>` convention, whose value is the policy code.
