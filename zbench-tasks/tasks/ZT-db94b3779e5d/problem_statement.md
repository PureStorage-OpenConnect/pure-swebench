## Add a `mentions:` search filter for finding messages that mention a specific user

### Current behavior

Zulip's search supports finding messages that mention *you* via the `is:mentioned` filter. However, there is no dedicated search operator for finding messages that mention *someone else*. To do that today, a user has to manually type the raw mention syntax as a full-text search term (e.g., searching for `"@**alya**"`), which is inconvenient and non-obvious.

### Expected behavior

Add a new `mentions:` search filter (e.g., `mentions:user`) so that searching for messages mentioning a particular user is a first-class search operation.

Requirements:

- **Typeahead/UI behavior:** The UI should work very similarly to the existing `dm-including:` filter. Once the user picks the `mentions:` filter in the search box, the typeahead should suggest users to choose from. User suggestions should be ordered the same way as they are for `dm-including:`.
- **Single user per filter:** The filter should only support a single user pill. To search for messages that mention multiple users, one can add multiple copies of the `mentions:` filter.
- **Result semantics:**
  - Silent mentions of the user should **not** be included in the results.
  - Group mentions or wildcard mentions that happen to include the user should also **not** be included — only direct, non-silent mentions of that specific user should match.
