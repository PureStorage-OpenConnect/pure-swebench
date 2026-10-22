# Bug: "Add emoji reaction" button wraps to a new line after the last reaction of an emoji is removed

## Context

In the Zulip web client, each message's reactions are rendered in a reactions row. Each individual emoji reaction rendered from the `message_reaction` template is wrapped in an outer element with class `.message_reaction_container`, and the row ends with the "add emoji reaction" (+) button.

## Current (buggy) behavior

When a user removes their reaction and they were the last person reacting with that emoji (its reaction count drops to zero), the client-side view update removes only the inner reaction element itself from the DOM. Its immediate parent — the `.message_reaction_container` wrapper — is left behind as an empty element in the reactions row.

This leftover empty wrapper still takes part in layout. A visible symptom: when a line of reactions is completely filled, removing an emoji reaction should free up enough space for the "add emoji reaction" (+) button to sit on the same line, immediately after the last remaining emoji. Instead, the empty wrapper keeps the (+) button pushed onto the next line. Reloading the page re-renders the message and the (+) button appears in the correct place, confirming this is purely a stale-DOM problem in the incremental view update, not a rendering/template problem.

## Required behavior

When the last user reacting with a given emoji removes their reaction (count reaches zero), the incremental view update must remove that reaction's entire outer wrapper — the `.message_reaction_container` element — from the DOM, not just the inner reaction element. After removal, no empty container element for that emoji may remain in the reactions row, so the "add emoji reaction" (+) button flows naturally to the position immediately after the last remaining emoji whenever there is room on the line.

All other behavior of removing a reaction (updating counts, tooltips, the case where other users still have the same reaction, etc.) must be unchanged.

## Interface requirements

- In the code path that updates the view when a reaction's count reaches zero (the "remove reaction from view" logic in the web client's reactions module), the DOM removal must be performed on the element obtained as the reaction element's **parent** (the `.message_reaction_container` wrapper), rather than calling remove on the reaction element itself. Concretely: locate the reaction element for the message and local emoji ID, take its parent container, and remove that parent from the DOM.
