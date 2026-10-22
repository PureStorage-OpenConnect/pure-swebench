# Don't repeat already-visible status text in right sidebar user tooltips

## Background

In the Zulip web app, the right sidebar shows the buddy list (user list). Users can set a status text (e.g., "out to lunch"). The buddy list has multiple display styles, configured via the `user_list_style` user setting (see `settings_config.user_list_style_values`): a "Compact" style that shows only the user's name, and styles such as "with status" that display the status text inline next to or under the user's name.

Hovering a row in the buddy list shows a tooltip. The tooltip content is built by the exported function `get_title_data` in `web/src/buddy_data.ts`, which returns a `TitleData` object with fields `first_line`, `second_line`, `third_line`, and (for individual users) `show_you` and `is_deactivated`. For an individual user with a status text set, the status text is currently always placed in `second_line`.

## Problem

When the buddy list is displayed in a style that already shows the status text inline, and the full status text fits (is not truncated/abbreviated), the tooltip repeats the exact same status text the user can already read in the sidebar. This is redundant noise.

## Required behavior

The tooltip for a buddy list row should include the user's status text only when the status text is *not* already fully visible in the sidebar row, i.e., only if at least one of these holds:

1. The user list is displayed in the "Compact" style (status text is not shown in the row at all).
2. The status text shown in the row is truncated/abbreviated because it is too long to fit (detect this at tooltip time from the rendered status element, e.g., by comparing its scroll width to its visible width).

In all other cases (status text shown inline and fully visible), the tooltip must omit the status text line. The rest of the tooltip content (name, "you" indicator, activity/last-active line, deactivated marker, group and bot handling) is unchanged in all cases.

The decision of whether the status is already visible must be made by the tooltip-invoking code (in the buddy list hover/tooltip handler, which has access to the current `user_list_style` setting and the rendered row's DOM), and passed into `get_title_data` — `get_title_data` itself should not inspect the DOM.

## Interface requirements

- The exported function `buddy_data.get_title_data(user_ids_string, is_group)` gains a third required boolean parameter `should_show_status`, so its signature becomes `get_title_data(user_ids_string: string, is_group: boolean, should_show_status: boolean)`.
- When `should_show_status` is false and the user has a status text set, the returned `TitleData.second_line` must be the empty string (the status text is suppressed); all other fields (`first_line`, `third_line`, `show_you`, `is_deactivated`) must be exactly what they would be with `should_show_status` true.
- When `should_show_status` is true, `get_title_data` behaves exactly as before: an individual user's status text appears in `second_line`, and results for groups, bots, and deactivated users are unchanged.

Callers of `get_title_data` must be updated to compute and pass `should_show_status` according to the rules above (true when the list style is Compact or the row's status text is abbreviated; false when the status text is fully visible in the row).
