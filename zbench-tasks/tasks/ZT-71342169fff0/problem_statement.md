# Improve “Organization default” dropdown labels in channel creation and channel settings

## Background

Several channel-level settings in the web app can be set to follow the organization-level default instead of a channel-specific value. These settings are edited via dropdowns in two places: the channel creation form and the channel settings (channel management) UI. Two such settings are relevant here:

- **Message retention period** — the channel-level setting can defer to the organization's message retention policy.
- **Topics policy** (shown in the UI as “Allow posting to the general chat topic?”) — the channel-level setting has an *inherit* value that defers to the organization-level topics policy (`realm_topics_policy`, whose values include `allow_empty_topic`, `disable_empty_topic`, etc.).

Currently, the option that defers to the organization setting does not consistently tell the user what the organization default actually is: the message retention dropdown uses a different string pattern for this option, and the topics-policy dropdown shows a bare “Organization default” label with no indication of the current organization value.

## Required behavior

For dropdown settings that offer the organization default as an option, the label for that option must follow this pattern:

> Organization default ({current value of the organization default})

where the parenthetical is the human-readable form of the organization's current setting value. Concretely:

1. **Message retention period** (channel creation and channel management dropdowns): update the string for the organization-default option to match the pattern above, showing the organization's current retention value (e.g. the number of days, or the label used for indefinite retention).
2. **“Allow posting to the general chat topic?”** (channel creation and channel management dropdowns): the “Organization default” option must include the organization's current value in parentheses — i.e. the human-readable label of whichever topics-policy option corresponds to the organization's current `realm_topics_policy`. For example, if the organization currently allows posting to the general chat (empty) topic, the option reads “Organization default (Enabled)”-style, using the same wording as the corresponding explicit option in that dropdown.
3. The parenthetical must reflect the organization's *current* value, so it must be computed from live realm state when the dropdown is rendered, not hard-coded.
4. Review the other dropdowns in channel creation and channel management that offer an organization-default option and apply the same label pattern where applicable, so the presentation is consistent.
5. No help center (documentation) changes are needed for the two settings named above.

## Implementation constraints

- Building the topics-policy dropdown labels requires resolving the organization's current topics policy from the realm state (`realm_topics_policy`). Any shared logic touched by this change that resolves a channel's effective topics policy — including the logic the compose box relies on to decide whether the empty / “general chat” topic is permitted — must read the organization-level value from `realm_topics_policy` on the realm state and behave correctly wherever it is invoked (compose paths as well as settings UI), for all valid values of that setting such as `allow_empty_topic`.
- Keep the existing behavior of the settings themselves unchanged; this task is about the labels shown to users and how the organization default is resolved for display, not about changing what any setting does.

## Interface requirements

(none)
