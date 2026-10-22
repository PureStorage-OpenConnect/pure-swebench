# Show channel privacy icons in the "Add new default channel" dropdown

## Background

In Zulip's organization settings, administrators can designate certain channels (streams) as *default channels* — channels that new users are automatically subscribed to. The default-channels settings page includes a dropdown widget for picking a channel to add as a new default channel.

Elsewhere in the web app, channel dropdowns (built on the `dropdown_widget` component) display a privacy/type icon next to each channel name (e.g., the hashtag icon for public channels, a globe for web-public channels, etc.). The "add new default channel" dropdown currently does **not** show these icons — it renders plain channel names only. It should be made consistent with the other channel dropdowns.

## Current behavior

- The `web/src/stream_data.ts` module exports a function `get_non_default_stream_names()` that returns the channels eligible to become default channels. Each returned element contains only `name` (the channel's name) and `unique_id` (the channel's `stream_id`).
- Because the dropdown options carry only a name and an id, the dropdown rendering code has no access to the underlying channel object, so it cannot render the appropriate privacy icon for each option. The dropdown shows bare channel names.

## Required behavior

1. Each option in the "add default channel" dropdown must display the channel's privacy/type icon next to its name, matching the appearance and icon logic used by other channel dropdowns in the app (public, web-public, etc.).
2. To enable this, the data provider for the dropdown must supply the full channel object with each option (see Interface requirements below).
3. Eligibility rules for which channels appear in the dropdown are unchanged: a channel is offered as an option only if it is **not already a default channel**, **not private** (`invite_only` is false), and **not archived**.
4. Selecting a channel from the dropdown must continue to work exactly as before (the option's `unique_id` remains the channel's `stream_id`).

## Interface requirements

- The `stream_data` module must export a function `get_default_stream_options()`, replacing the former `get_non_default_stream_names()`, that returns the channels eligible to be added as default channels: all channels that are not already default, not private (invite_only), and not archived. All callers of the old function must be updated.
- Each element of the array returned by `get_default_stream_options()` must be an object with exactly three fields:
  - `name` (string): the channel's name,
  - `unique_id` (number): the channel's `stream_id`,
  - `stream`: the full `StreamSubscription` object for that channel,
  so that consumers such as the default-channels settings UI can access complete channel data for each option.

### Example

Given a non-default, non-archived public channel named `public` with `stream_id` 102 whose subscription object is `public_stream`, `get_default_stream_options()` must return an array containing `{name: "public", unique_id: 102, stream: public_stream}`; a private (invite-only) channel or an existing default channel must not appear in the result.

## Where to look

- `web/src/stream_data.ts` — the eligible-channels provider function.
- The default-channels settings code (under `web/src/settings_streams.*` or similar) — where the dropdown widget for adding a default channel is constructed; wire it to use the `stream` field so each option renders with its privacy icon, following the pattern used by other channel dropdowns built on the dropdown widget.
