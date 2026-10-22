# Add a "Permissions" tab to channel settings

## Background

In the Zulip web app, opening a channel's settings (the right-side channel overlay reached from the channels list) currently shows a set of tabs such as **General**, **Subscribers**, etc. Today, the **General** tab contains, among other things:

- A "Who can access this channel" (privacy/access) setting,
- A "Channel details" section (including "Created by ..." information),
- A "Folders" section for assigning the channel to a channel folder,
- A "Default channel for new users" setting,
- An "Advanced configuration" heading grouping several permission-related subsections (e.g., posting/administration permissions and other group-permission settings).

We want to reorganize this so that permission-related settings live in their own dedicated tab.

## Required behavior

### New "Permissions" tab

- Add a **Permissions** tab to the channel settings tab strip, positioned immediately to the right of the existing tabs.
- The tab must be addressable by URL: navigating to the channel settings with the `/permissions` path suffix (i.e., the hash/URL section `permissions`, parallel to how the existing tabs like `general` are addressed) must open this tab directly, and switching to the tab must update the URL accordingly.
- Contents of the Permissions tab:
  - The "Who can access this channel" setting moves here from the General tab and becomes the **first** setting, placed under a "Subscription permissions" section.
  - Everything that currently lives under the "Advanced configuration" heading moves here. The "Advanced configuration" heading itself is **removed**; each of its former subsections becomes a top-level section within the Permissions tab.

### Reorganized "General" tab

- Move the "Channel details" section **above** the "Folders" section.
- Move the "Default channel for new users" setting into the "Channel details" section, placed just below the "Created by ..." line.
- The settings moved to the Permissions tab no longer appear in the General tab.

### Settings save/discard behavior must remain correct

All of the relocated settings use the standard live-update settings framework: editing a setting in a subsection reveals a Save/Discard button pair for that subsection, and the change-detection logic scans the subsection for property-input widgets to decide whether anything differs from the saved state.

After this reorganization, the General tab contains the channel **folder** widget, which is rendered as a pill container but is *not* one of the standard property-element settings (it manages its own saving). The unsaved-changes detection must not be confused by such widgets — see the interface requirement below. Concretely: typing in or modifying the folder widget's pill container must not be picked up by the generic subsection change-tracking, while genuine group-permission pill widgets (e.g., "who can post", "who can administer" style settings) must continue to correctly trigger and clear the Save/Discard state.

## Interface requirements

- Unsaved-changes detection for a settings subsection must identify group-permission setting widgets by selecting elements matching `.pill-container.prop-element` (pill containers that are marked as property elements via the pre-existing `prop-element` class), so that pill containers which are not property elements (e.g., the channel folder widget's pill container) are excluded from save-button change tracking.

## Notes

- Update the relevant help center documentation (pages describing where channel permission settings are found) to reflect the new tab and layout.
- No changes to the server API are required; this is a web-client reorganization of where existing settings are displayed and how they are tracked for unsaved changes.
