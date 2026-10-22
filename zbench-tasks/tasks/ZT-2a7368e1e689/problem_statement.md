# Support multiple users in `dm-including` search pills and operator

## Background

Zulip's web client has a search/narrow system built on operators. Two related operators deal with direct messages:

- `dm:` narrows to a direct-message conversation with an exact set of recipients. Its operand supports a comma-separated list of user emails, and in the search box its input pill supports multiple users: after selecting a user from the typeahead, typing a `,` lets you add another user, and typing a name suggests matching users to append to the same pill.
- `dm-including:` narrows to all messages in direct-message conversations that include a given user (in any conversation, regardless of the other participants).

## Current behavior

The `dm-including` operator and its search pill only support a **single** user:

- The operand is treated as a single email; there is no support for a comma-separated list of users.
- In the search input, once a user has been selected from the typeahead for a `dm-including:` pill, there is no way to add additional users to that pill (no comma-to-add behavior, no typeahead suggestions for further users), unlike `dm:` pills.

## Required behavior

### 1. Operator semantics

The `dm-including` operator must accept a comma-separated list of user emails as its operand (e.g. `dm-including:a@x.com,b@y.com`). The resulting narrow must match messages in direct-message conversations whose recipients include **all** of the listed users (the listed users must each be among the message's DM recipients; other participants may also be present). Single-email operands must continue to work exactly as before. Everything that consumes this operator — operand parsing/canonicalization, narrow filtering, narrow titles/descriptions, and URL encoding/decoding of the search — must handle the multi-user form consistently.

### 2. Search pill / typeahead behavior

`dm-including:` pills in the search box must behave like `dm:` pills with respect to adding users:

- After a user selects a name from the typeahead for a `dm-including:` pill, typing a `,` must let them add more users to the same pill.
- Starting to type a name after that must suggest matching users to add.
- Users already in the pill should not be re-suggested, mirroring the `dm:` pill behavior.

### 3. Empty-narrow banner messaging

When a `dm-including` narrow has no messages to display, an empty-narrow banner is shown. Its title must be chosen as follows:

- If the operand is a single email that does not correspond to an existing user, keep the existing wording: **"This user does not exist!"** (translated).
- If the operand contains multiple comma-separated emails and at least one of them does not correspond to an existing user, the banner title must be **"User {email} does not exist!"** (translated), where `{email}` is a nonexistent email from the list. For example, for `dm-including:false@blah.com,foo@fake.com` where `false@blah.com` is not a real user, the title must be exactly `User false@blah.com does not exist!`.

Existing empty-narrow messages for `dm-including` in other situations (e.g. all users exist but there are no matching messages) must be preserved.

## Interface requirements

- The `dm-including` search/narrow operator must accept a comma-separated list of user emails as its operand (e.g. `dm-including:a@x.com,b@y.com`), matching messages whose direct-message recipients include all of the listed users.
- When an empty-narrow banner is rendered for a `dm-including` filter whose operand contains multiple comma-separated emails and at least one email does not correspond to an existing user, the banner title must be the user-facing message "User {email} does not exist!", where `{email}` is the nonexistent email address (e.g. "User false@blah.com does not exist!"). The pre-existing single-operand wording "This user does not exist!" must be retained for the single-email case.

## Notes for implementation

- Look at how the `dm` operator implements comma-separated operands and how its search pill implements multi-user entry; `dm-including` should follow the same patterns wherever they apply.
- All banner strings above are user-facing and must go through the standard translation machinery.
