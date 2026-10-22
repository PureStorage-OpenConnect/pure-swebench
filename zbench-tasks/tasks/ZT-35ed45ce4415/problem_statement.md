# Send Welcome Bot onboarding messages to users created by realm import

## Background

Zulip can create a new realm by importing data from third-party chat tools (Slack, Mattermost, Rocket.Chat, and any other source that goes through the common realm-import pipeline). When a user signs up for Zulip normally, Welcome Bot sends them the standard onboarding direct message(s) explaining how to get started, so their first experience includes a populated conversation with Welcome Bot.

## Current behavior

Users whose accounts were created via a data import never receive these onboarding messages. When such a user logs into Zulip for the first time, the Welcome Bot conversation in their direct-message list is completely empty, which is confusing and inconsistent with the normal new-user experience.

## Required behavior

As part of completing a realm import, every imported human user account must receive the same Welcome Bot onboarding direct message(s) that a newly registered Zulip user would receive:

- The messages must be sent from Welcome Bot to each imported user as one-to-one direct messages, with the same content that Welcome Bot sends to a brand-new user on signup (including rendered content, i.e., the messages must be fully rendered like any other delivered message).
- This must happen in the shared import pipeline so it applies uniformly to all supported import sources (Slack, Mattermost, Rocket.Chat, etc.), not be reimplemented per-importer.
- Only real human user accounts should receive the messages. Bots, mirror-dummy accounts, and deactivated users must not receive Welcome Bot onboarding messages.
- The messages are ordinary messages in the imported realm: they must appear in the realm's message table alongside the imported history, be addressed to the correct per-user direct-message recipients, and show up in each user's Welcome Bot conversation when they open the app.
- Imported message content and counts must otherwise be unaffected — the only new messages added by this change are the Welcome Bot onboarding direct messages, one set per eligible imported user.

### Concrete example

After importing a workspace containing N active human users, opening any of those accounts should show the standard Welcome Bot onboarding conversation (identical text to what a fresh signup on that server would see), and the realm's total message count should equal the imported history plus the onboarding direct messages for those N users.

## Notes

- The onboarding messages should be generated at import time (when the imported realm's data is finalized), not lazily on first login.
- Reuse the existing logic that produces Welcome Bot's onboarding messages for new signups, so the content stays in sync if that copy changes in the future.

## Interface requirements

(none)
