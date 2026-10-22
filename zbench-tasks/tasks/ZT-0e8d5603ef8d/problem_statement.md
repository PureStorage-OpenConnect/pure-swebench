# Add a channel-level permission setting for who can start new topics

## Background

Zulip channels (streams) already carry several group-based permission settings, such as `can_send_message_group` ("Who can post"), `can_administer_channel_group`, `can_add_subscribers_group`, and `can_remove_subscribers_group`. Each of these stores the id of a user group (system or user-defined), and a user holds the permission iff they are a member of that group, directly or via subgroups. The server publishes the configuration of each such setting (which groups are permitted as values, the default, etc.) in its supported permission-settings metadata for channels.

Currently there is no way to restrict who may *start new topics* in a channel: anyone who can post can also create a topic. Some organizations want channels where members can reply within existing topics but only a restricted group can open new ones.

## Required behavior

### New channel permission field

Add a new group-based channel-level permission, `can_create_topic_group`, holding the id of the user group whose members are allowed to start new topics in that channel.

- Default value: everyone including guests (the `role:everyone` system group).
- All group choices are allowed, including "Nobody" (which locks the channel down to its existing topics) and user-defined groups.
- The field must be delivered to web clients on channel/stream objects alongside the existing permission-group fields, so client-side data structures for a subscription include `can_create_topic_group`.
- The server's supported permission-settings metadata for channels must include a `can_create_topic_group` entry configured as: system groups not required to be the only option is **false** — i.e., `require_system_group: true`; `allow_internet_group: false`; `allow_nobody_group: true`; `allow_everyone_group: true`; default group name `role:everyone`; and no restricted allow-list of system groups (empty `allowed_system_groups`).

### Semantics

- The permission controls creating *any* new topic in the channel, including the "general chat" (empty-string) topic when no messages exist there yet.
- A user without this permission also must not be able to move messages *into* a topic that does not yet exist in the channel (moving messages creates a topic just like posting does).
- Resolving or unresolving a topic (for users otherwise permitted to do so) does **not** require this permission, even though it renames the topic.
- Where questions arise about interactions with other permissions, the existing "Who can post" (`can_send_message_group`) behavior is the model to follow.
- The setting cannot be configured (i.e., must remain "everyone") for channels with protected history, and conversely protected history cannot be enabled while this setting restricts topic creation. In the channel settings UI, the disabled topic-permission control should show the tooltip "Everyone can start topics in channels with protected history.", and the disabled protected-history control should show "You must allow everyone to start new topics in this channel in order to turn on protected history."

### Channel settings UI

- Add the setting to the channel permission settings with label "Who can start new topics", placed immediately after "Who can post".

### Web client permission check

The web client needs a single authoritative check for this permission (see Interface requirements). Its result must be:

- `true` iff the current user is a member — directly or transitively via subgroups — of the channel's `can_create_topic_group`.
- Guests are allowed when they are members of the group (e.g. when the group is everyone-including-guests).
- Always `false` for spectators (logged-out web-public viewers), regardless of the group value.
- Always `false` for archived channels.

### Compose and message-move behavior in the web app

For a channel where the current user lacks this permission:

- **Topic typeahead:** the compose box's topic typeahead normally prepends the user's typed query as a synthetic "new topic" suggestion at the top of the list when the query doesn't exactly match an existing topic (this happens when there are other suggestions being shown). When the user lacks permission to create topics in the selected channel, that synthetic query suggestion must be suppressed — only existing topics are offered. When the user has the permission, the existing prepend behavior is unchanged.
- **Compose validation:** sending a message to a topic that does not yet exist in such a channel must be blocked, with the Send button disabled and an explanatory tooltip/banner: "You are not allowed to start new topics in this channel. Choose an existing topic from the typeahead." Sending to an existing topic remains allowed (subject to the usual posting permission).
- **Closed-compose "Start new conversation" button:** when the currently selected compose destination is a channel where the user lacks this permission, clicking the button should open the compose box with the channel picker open instead of a blank new-topic compose to that channel.
- **Left sidebar "New topic" button:** disabled for such channels, with tooltip "You are not allowed to start new topics in this channel."
- **Message moves:** attempting to move messages into a new (nonexistent) topic in such a channel should be blocked in the move-topic dialog, or failing that, produce a clear error.

The permission check must be consulted wherever the client decides whether compose may proceed (compose start/validation paths use it alongside the existing `can_post_messages_in_stream` check).

## Interface requirements

- Channel (stream) objects gain a new server-provided permission field `can_create_topic_group`: the id of a user group (system or user-defined) whose members are allowed to start new topics in that channel.
- The server's supported permission settings for channels include an entry `can_create_topic_group` configured with: `require_system_group: true`, `allow_internet_group: false`, `allow_nobody_group: true`, `allow_everyone_group: true`, default group `role:everyone`, and no restricted list of allowed system groups.
- The web client's `stream_data` module exposes a new permission-check function `can_create_new_topics_in_stream(stream_id)` returning a boolean: `true` iff the current user is a member (directly or via subgroups) of the channel's `can_create_topic_group`. Guests are allowed when they are members of that group; it always returns `false` for spectators (logged-out viewers) and for archived channels.
- In the compose box topic typeahead, when the current user lacks permission to create new topics in the selected channel, the typed query must NOT be offered as a synthetic new-topic suggestion at the top of the suggestion list; when the user does have permission, the existing behavior of prepending the query (when it matches no existing topic exactly) is preserved.
