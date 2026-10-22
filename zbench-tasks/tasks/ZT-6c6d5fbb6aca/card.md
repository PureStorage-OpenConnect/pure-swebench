# ZT-6c6d5fbb6aca -- people: Use Intl.ListFormat rather than .join(",").

- lang: web   issue: #26936   tier: B
- fix: https://github.com/zulip/zulip/commit/6c6d5fbb6acaf984679ba8ce6e8b7d0f35dd6c01
- f2p: web/tests/buddy_data.test.cjs, web/tests/people.test.cjs
- p2p: web/tests/pm_list_data.test.cjs

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior-affecting refactor (i18n list formatting)",
  "reason": "Real engineering task (high-priority i18n issue) with an observable behavior change: recipient lists now render via Intl.ListFormat ('A and B') instead of .join(', ') ('A, B'), and get_recipients changes return type to string[]. The hidden tests assert exactly this new observable output on short, deterministic strings \u2014 they fail before and pass after. Not i18n string churn (no translation files touched), and not a brittle snapshot: the pinned strings are the precise behavior under test, not incidental formatting."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "people.get_recipients(user_ids_string) changes its return type from a comma-joined string to an array of recipient display names, sorted alphabetically; callers that need a display string must join/format the array themselves",
    "For a direct message with oneself, people.get_recipients returns a one-element array containing the current user's full name",
    "Muted users appear in the people.get_recipients result as the translated 'Muted user' placeholder name, occupying their own array element",
    "The group DM title (first line of buddy_data.get_title_data for groups) renders recipient names as a natural-language list with a conjunction, e.g. two users render as 'Human Selma and Old User' instead of 'Human Selma, Old User'"
  ],
  "reason": "The test binds to two things: the user-visible group-title formatting ('X and Y' conjunction list) and the changed return shape of people.get_recipients, a pre-existing exported cross-module API. The formatting change is plainly user-facing behavior a ticket would state. The get_recipients change is a signature/semantics change to an existing public module function, which a design brief could legitimately dictate ('return the sorted name array; format at call sites'). Notably, the test does NOT reference the fix's newly invented internals (format_recipients, format_array_as_list_with_conjuction, the 'long'/'narrow' join_strategy enum), so no private implementation choices leak into the test. With the contract items above in the brief, the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the goal (replace user-facing .join(\", \") with Intl.ListFormat), and the evidence pins down concrete, checkable outcomes: get_recipients returns a sorted array (including self-DM and muted-user placeholder cases) and group DM titles use conjunction-formatted lists (\"A and B\"). Combined with the interface requirements, two engineers would produce compatible implementations."
}
