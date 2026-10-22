# Make the sender configurable when generating a channel email address

## Background

Zulip lets users generate a special email address for a channel (the "Generate channel email address" modal, reachable from the channel/stream settings menu). Any email forwarded to that address is ingested by the incoming email gateway and posted to the channel. Today the resulting Zulip message is always posted by the system "Email Gateway" bot; the user has no way to choose a different sender, and the modal does not consider whether anyone would actually be allowed to post to the channel.

## Required behavior

### 1. Sender selector in the modal

Add a selector at the top of the "Generate channel email address" modal that chooses which user the forwarded email will be sent by.

- Label: **"Who will send the message?"**
- Options, in exactly this order:
  1. The **Email Gateway bot** — this is the default selection.
  2. The **current user**.
  3. Each **bot owned by the current user** (omitted entirely if the user owns no bots).

The choice of sender must be encoded into the generated channel email address itself (the address is the only artifact the gateway sees later), so that:

- An email forwarded to an address generated with a given sender is posted to the channel **as that sender** (the resulting message's sender is the selected user/bot, not unconditionally the Email Gateway bot).
- **Backward compatibility:** channel email addresses generated before this change (which carry no sender information) must continue to work and continue to post as the Email Gateway bot. Selecting the Email Gateway bot explicitly must behave identically.

### 2. Posting-permission enforcement in the modal

Apply the channel's message-sending permissions to this feature:

- If the current user does **not** have permission to send messages to the channel, and **none** of the bots they own has permission either, the "Generate email address" button must be disabled, with a tooltip explaining why (e.g. that they do not have permission to post in the channel).
- If the current user cannot post but one or more of their bots can, the selector should offer only the senders that are actually allowed to post (i.e. hide the current user and any bots without permission, keeping the bots that can post).

The Email Gateway bot option is the system default and is not subject to the per-user filtering above.

### 3. Email Gateway bot must be available to the web client

For the modal to offer (and render) the Email Gateway bot as a sender, the web client must actually know about it. The Email Gateway bot must be delivered to clients as one of the realm's **cross-realm system bots** (alongside the existing ones such as the Welcome bot and Notification bot), and the client-side user/people data layer must treat it like any other cross-realm bot:

- It is registered as a bot user (`is_bot: true`) and therefore appears in the client's list of known bot user IDs.
- It is looked up successfully by its email address and displays its full name ("Email Gateway").
- As a cross-realm bot it has **no owner**: asking for its bot owner yields no user (undefined), rather than an error or a placeholder owner.
- It does not count toward the realm's active human-user count.
- It remains visible/accessible even in realms where a user's ability to access all other users is restricted (system bots are always accessible, like other cross-realm bots).

### 4. Documentation

Update the user-facing help documentation for the message-a-channel-by-email feature to describe the new sender option and the permission behavior.

## Acceptance summary

- The modal shows the "Who will send the message?" selector with Email Gateway bot preselected, then the current user, then the user's own bots, in that order.
- Addresses encode the chosen sender; ingested emails post as that sender; legacy addresses still post as the Email Gateway bot.
- The generate button is disabled with an explanatory tooltip when neither the user nor any bot they own may post to the channel; when only some candidate senders may post, only those are offered.
- The Email Gateway bot is exposed to web clients as an ownerless cross-realm system bot, retrievable by email, counted among bots and not among active humans.

## Interface requirements

(none)
