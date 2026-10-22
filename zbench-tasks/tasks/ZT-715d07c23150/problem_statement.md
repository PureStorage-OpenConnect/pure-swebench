# Allow realm administrators to set another user's status via the API

## Background

Zulip users can set a personal status (a short `status_text`, an optional status emoji, and a deprecated `away` flag) via the existing endpoint `POST /json/users/me/status`. Organizations that want to automate status changes (for example, setting everyone who is in a meeting to "In a meeting") currently have no way to do this centrally: the only write endpoint is self-service, so an integration would need to collect a personal API key from every user. There is already a read endpoint, `GET /json/users/{user_id}/status`, for fetching another user's status, but no corresponding write endpoint.

## Required behavior

Add a new endpoint:

```
POST /json/users/{user_id}/status
```

that lets a **realm administrator** update the status of the user identified by `user_id` in their realm.

### Access control

- If `user_id` does not correspond to an accessible user in the realm, the request must fail with the standard error message `No such user` (the same wording used by the existing user-by-id endpoints).
- If the requester is **not** a realm administrator and targets another user, the request must fail with the standard error message `Insufficient permission` (the same wording used by existing admin-only per-user endpoints).

### Request semantics

The endpoint accepts exactly the same parameters as `POST /json/users/me/status` — `status_text`, `emoji_name`, `emoji_code`, `reaction_type`, and `away` — and must apply identical validation, normalization, and error behavior, applied to the **target** user rather than the requester. Concretely, all of the existing semantics must hold when going through the new endpoint:

- A request with no parameters fails with `Client did not pass any new values.`
- `status_text` is trimmed of leading/trailing whitespace before being stored (e.g. `"   at the beach  "` is stored as `"at the beach"`).
- A `status_text` longer than 60 characters fails with `status_text is too long (limit: 60 characters)`.
- Passing `emoji_code` or `reaction_type` without `emoji_name` fails with `Client must pass emoji_name if they pass either emoji_code or reaction_type.`
- Emoji validation matches the self-service endpoint: an unknown emoji name fails with `Emoji '<name>' does not exist`; an emoji name that does not match the supplied `emoji_code` fails with `Invalid emoji name.`; a `reaction_type` of `realm_emoji` with a code that is not a valid custom emoji fails with `Invalid custom emoji.`
- Passing `emoji_name` alone causes the server to fill in the matching `emoji_code` and `reaction_type` (e.g. `emoji_name="car"` results in `emoji_code="1f697"` with the unicode-emoji reaction type).
- Passing an empty `emoji_name` (`emoji_name=""`) clears the status emoji: the resulting state has empty `emoji_name` and `emoji_code`, with `reaction_type` reset to the unicode-emoji type.

### Effects of a successful update

- The update is applied to the **target** user's status, and a subsequent `GET /json/users/{user_id}/status` for that user must reflect the new values.
- The server must emit the pre-existing `user_status` realtime event, with the same schema as updates made through `/users/me/status`, and with `user_id` set to the **target** user's ID — not the acting administrator's.
- Setting `away=true` must apply the existing deprecated `away` semantics to the **target** user: in addition to reporting `away: true` in their status, it sets that user's `presence_enabled` personal setting to `False` (mirroring the documented behavior of `POST /users/me/status`). The corresponding extra events that a self-service `away` change produces (the status event plus the associated user-setting update events) must likewise be emitted for the target user.

## Interface requirements

- A new API endpoint `POST /json/users/{user_id}/status` lets a realm administrator update another user's status; it accepts the same request parameters as the existing `POST /json/users/me/status` endpoint (`status_text`, `emoji_name`, `emoji_code`, `reaction_type`, `away`) with identical validation, whitespace-trimming, emoji-fill, and error-message semantics.
- Requests to the new endpoint for a nonexistent `user_id` must fail with the standard error message `No such user` (the same wording already used by existing user-by-id endpoints).
- Requests by a non-administrator targeting another user must fail with the standard error message `Insufficient permission` (the same wording already used by existing admin-only user endpoints).
- A successful update through the new endpoint must emit the pre-existing `user_status` event schema with `user_id` set to the target user (not the acting administrator), and the target user's status as returned by `GET /json/users/{user_id}/status` must reflect the change.
- Setting `away=true` through the new endpoint must apply the existing deprecated `away` semantics to the target user, i.e. set that user's `presence_enabled` setting to `False` (matching the documented behavior of `POST /users/me/status`).
