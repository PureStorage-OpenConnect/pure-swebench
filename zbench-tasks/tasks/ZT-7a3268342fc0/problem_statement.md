# Export and import the `zerver_submessage` table in Zulip's realm export/import

## Background

Zulip's interactive widget messages — polls (created with `/poll ...`) and to-do lists (created with `/todo ...`) — store their widget data in the `SubMessage` model (database table `zerver_submessage`). Each such message has one or more `SubMessage` rows carrying the widget payload, e.g. a row with `msg_type="widget"` and JSON `content` like `{"widget_type": "todo", "extra_data": {"task_list_title": "Example Task List Title", "tasks": []}}`.

## Current behavior (bug)

The realm export/import system (`zerver/lib/export.py` and `zerver/lib/import_realm.py`) currently lists `zerver_submessage` among the deliberately non-exported tables (`NON_EXPORTED_TABLES`). As a result:

- Realm exports contain the poll/to-do messages themselves but none of their `SubMessage` rows.
- After importing such an export into another server, messages that contained polls or to-do lists no longer render as working widgets — the widget data is simply missing in the imported realm.

## Required behavior

1. **Realm export includes submessages.** `zerver_submessage` must be moved out of the non-exported set and exported as part of a full realm export, alongside the messages it belongs to. Exported records must carry the row's `id`, `sender`, `msg_type`, `content`, and `message` fields.

2. **Realm import restores submessages.** When importing a realm export, `SubMessage` rows must be recreated with correct foreign-key remapping:
   - `message` must point to the corresponding imported `Message` row (message IDs change across import).
   - `sender` must point to the corresponding imported `UserProfile` in the new realm.

3. **Widgets survive a round trip.** After exporting a realm containing a poll message and a to-do message and importing it into a fresh realm:
   - Each imported widget message has the same number of `SubMessage` rows as the original (e.g. one widget submessage per freshly created poll/to-do message).
   - The imported submessage's `content` is JSON-equivalent to the original submessage's `content`, and its `sender` is the imported counterpart of the original sender.
   - The imported message's `rendered_content` is HTML-equivalent to the original message's `rendered_content`, so polls and to-do lists render properly in the imported realm.

4. **Single-user export includes submessages.** The single-user (user data) export must also produce a `zerver_submessage` data set containing the submessages attached to messages included in that export, with each record containing exactly the fields `id`, `sender` (user ID), `msg_type`, `content` (raw JSON string), and `message` (message ID). For example, a to-do message created with `/todo Example Task List Title` yields a record with `msg_type="widget"` and `content` equal to `{"widget_type": "todo", "extra_data": {"task_list_title": "Example Task List Title", "tasks": []}}`.

## Notes for implementation

- Follow the existing patterns in the export/import code for message-scoped tables (tables keyed by `message_id`, such as `zerver_reaction`) for both the realm export/import path and the single-user export path.
- Ensure ID allocation/remapping tables in the import path cover `SubMessage` so primary keys and foreign keys are consistently re-mapped.
- Update any export tooling documentation/comments that enumerate exported vs. non-exported tables so `zerver_submessage` is accounted for as exported.
