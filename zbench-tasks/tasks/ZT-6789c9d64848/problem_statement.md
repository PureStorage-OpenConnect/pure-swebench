# Add a clear ("x") button to table filter/search inputs in settings

## Background

Zulip's settings pages contain many tables (users, streams, linkifiers, etc.) whose rows can be narrowed via a small text filter input. These filter inputs are wired up through the shared list widget module (`web/src/list_widget.ts`), which accepts an optional filter configuration (`opts.filter.$element`) and re-renders the list as the user types.

## Current behavior

Once a user types text into one of these filter boxes, the only way to clear it is to manually select and delete the text. There is no one-click affordance to reset the filter.

## Required behavior

Each table filter/search input managed by the list widget must gain an "x" (clear) button:

1. **Markup.** The clear button is rendered as a sibling element of the filter input, identified by the CSS class `clear-filter`. To keep markup consistent across the many settings tables, introduce a shared Handlebars template partial named `filter_text_input` that renders the input together with its clear button, and use it wherever these filter inputs appear. The button's icon should use the classes `zulip-icon zulip-icon-close`.
2. **Visibility.** The clear button must be visible only when the input is non-empty. When the input is empty (including immediately after being cleared), the button must be hidden.
3. **Click behavior.** Clicking the clear button must: set the filter input's value to the empty string, reset the widget's internal filter value to the empty string, and redraw the list. After clicking clear, the widget must display the full unfiltered list — i.e., `widget.get_current_list()` returns the complete original list. Typing into the input again after clearing must filter the list normally.
4. **Event wiring.** In `ListWidget.create`'s event setup, when a filter element is configured, bind a direct `click` handler on the clear button obtained via `opts.filter.$element.siblings(".clear-filter")`. This must be a direct handler on that element, not a delegated handler on a container.
5. **Handler cleanup.** The list widget's `clear_event_handlers` logic (which runs when `ListWidget.create` is invoked again on the same container) must also unbind the clear-button handler by calling `.off("click")` on the element obtained via `$element.siblings(".clear-filter")`, alongside the existing cleanup of the input, sort, and scroll handlers. Creating a widget on a container that never had one must not attempt any cleanup side effects.

## Interface requirements

- Each list-widget filter/search input gains a clear button rendered as a SIBLING element of the input, identified by the CSS class `clear-filter` (introduced via a shared `filter_text_input` template partial).
- In `ListWidget.create`'s event setup, when a filter element is configured, the widget binds a direct `click` handler on the clear button obtained via `opts.filter.$element.siblings(".clear-filter")` (not a delegated container handler).
- Clicking the clear button empties the filter input (sets its value to ""), resets the widget's filter value to the empty string, and redraws, so that `widget.get_current_list()` returns the full unfiltered list afterwards.
- `clear_event_handlers` (invoked when `ListWidget.create` is called again on the same container) must also unbind the clear-button handler by calling `.off("click")` on the element obtained via `$element.siblings(".clear-filter")`, alongside the existing input/sort/scroll handler cleanup.

## Scope notes

- The change applies to the filter boxes for tables in the settings UI; the shared template partial and list-widget wiring are the mechanism, so all list-widget-backed filter inputs that adopt the partial get the behavior.
- Styling should place the "x" inside/adjacent to the input in the conventional position for a clearable search field, matching existing Zulip visual patterns.
