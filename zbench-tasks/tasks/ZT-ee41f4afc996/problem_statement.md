## Allow `@`-prefix when adding a user group to a channel

### Observed behavior

In the input pill / typeahead used to add subscribers to a channel (stream), user groups do not appear in the typeahead suggestions when the query begins with `@`. Users accustomed to `@`-mentioning groups elsewhere in the app find this confusing: typing `@` followed by a group name yields no group match, even though the same group would be suggested if the query were typed without the `@` prefix.

### Expected behavior

1. User groups should be matched in the add-subscribers typeahead whether or not the query starts with an initial `@`. Typing `@marketing` should match the `marketing` group just as typing `marketing` does.
2. When the query begins with `@`, the typeahead shows **only** user groups: individual users are excluded from the suggestions, and a `@`-prefixed query must not match any user. The leading `@` is stripped before the group name is matched and before sorting, so `@marketing` matches the `marketing` group, and the sorter receives the query without the `@`.

### Scope

These changes should apply to both places where subscribers can be added:

- the channel (stream) creation flow, and
- the channel (stream) editing / settings flow.
