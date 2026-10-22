# Add support for editing and deleting channel folders in the web app

## Background

Zulip's web client supports organizing channels into "channel folders". Folders can currently be created, and channels can be assigned to a folder via a dropdown widget (the one used for adding channels to a folder). However, once a folder exists there is no way in the UI to rename it, change its description, or delete it.

## Required behavior

Add edit and delete affordances for channel folders, modeled on the existing UI pattern used for saved snippets (where hovering a row in the popover/dropdown reveals inline action icon buttons).

### Dropdown row actions

In the dropdown widget for assigning channels to a folder, each folder option row must show, on hover, two icon buttons:

- An **edit** button with the tooltip "Edit folder".
- A **delete** button with the tooltip "Delete folder".

Clicking each button opens a modal dialog (and should not simply select that folder in the dropdown).

### Edit modal

- Title: **"Edit channel folder"**.
- Contains two inputs, prefilled with the folder's current values:
  - **Channel folder name** (single-line text input).
  - **Description** (text area).
- Buttons: **Cancel** and **Confirm**.
- On confirm, the client sends the changed name and/or description to the server via the existing channel-folder update API (`PATCH /json/channel_folders/{folder_id}` with `name` and/or `description` parameters — only fields that actually changed need to be sent). The local folder data and any UI displaying the folder must reflect the server-propagated update.

### Delete modal

- Title: **"Delete channel folder?"**.
- Body text: "Channels in this folder will become uncategorized. This action cannot be undone."
- Buttons: **Cancel** and **Confirm**.
- On confirm, the folder is deleted/archived via the server API, and every channel that was in the folder becomes uncategorized (its `folder_id` becomes null). Note that the server may require folders to be emptied of channels before deletion — in that case the client is responsible for moving the folder's channels out of the folder (using the bulk/individual channel-update API to clear `folder_id`) as part of the confirm action, before or together with deleting the folder itself.
- All translatable strings above must go through the standard i18n mechanisms.

### Folder membership lookup

To support the delete flow (and other frontend features that need to know which channels are in a folder, e.g. stream settings), the client must expose a way to look up a folder's channels from the client-side stream data.

## Interface requirements

- The `channel_folders` web module (`web/src/channel_folders.ts`) must export a function `get_stream_ids_in_folder(folder_id: number): number[]`, intended as the cross-module API for other frontend components (e.g. stream settings) to look up a folder's channels.
- `get_stream_ids_in_folder` returns the `stream_id` of every known/registered stream whose `folder_id` equals the given folder ID; streams with a different `folder_id`, or with a null `folder_id`, are excluded.
- When no streams belong to the folder, `get_stream_ids_in_folder` returns an empty array (never null/undefined).
- The returned stream IDs must appear in the order the streams were registered in the client's stream data store — insertion order, with no additional sorting applied.
