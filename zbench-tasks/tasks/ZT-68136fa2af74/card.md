# ZT-68136fa2af74 -- integrations: Add support for emoji events in GitLab design comments.

- lang: py   issue: #34221   tier: B
- fix: https://github.com/zulip/zulip/commit/68136fa2af74a9d66cbcee4aca4ce179d3d541b2
- f2p: zerver.webhooks.gitlab.tests.GitlabHookTests.test_emoji_award_in_design_note, zerver.webhooks.gitlab.tests.GitlabHookTests.test_emoji_revoke_in_merge_request_note_with_custom_topic
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "feature",
  "reason": "Real integration feature (GitLab emoji events on design comments) with a deterministic fixture-driven grader: check_webhook asserts the exact topic and message the webhook produces, which IS the observable behavior of the change \u2014 short, stable strings, not an incidental snapshot. Fails before the fix (design-note emoji payloads mishandled) and passes after."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The GitLab webhook integration must handle Emoji Hook award/revoke events whose awardable is a comment on a design (payload has object_attributes.awardable_type = \"Note\" and note.noteable_type = \"DesignManagement::Design\", with object_attributes.awarded_on_url null); at present such payloads are not handled.",
    "For emoji events on design comments, the Zulip topic must be \"<repo name> / design <design filename>\" (e.g. \"sample / design Sample.png\"), matching the topic format already used for design-comment note events; note that no \"#\" sign precedes the design name, since designs are identified by filename rather than numeric ID.",
    "For emoji events on design comments, the message must follow the existing emoji-event wording \u2014 \"<user full name> added the emoji :<emoji name>: to [a comment](<url>).\" for award (\"removed ... from\" for revoke) \u2014 where <url> is the design comment's URL derived from the note payload the same way as for existing design-comment events: <project web_url>/-/issues/<issue>/designs/<design filename>#note_<note id>.",
    "When the webhook URL includes a custom topic= parameter, emoji award/revoke events must continue to use that topic and prefix the message with the repository link in the form \"[[<repo name>](<project web_url>)] \" (existing include-title behavior must be preserved for emoji events on merge request comments)."
  ],
  "reason": "The test only exercises the pre-existing webhook endpoint via check_webhook and asserts user-visible topic/message strings; the fixture is supplied by the test itself. None of the fix's internal choices (helper names, new function parameters, skip_previews entries) leak into the test. But the asserted topic format, message wording, URL construction, and the no-'#' convention for designs are new user-visible outputs a solver could not produce without being told, so they must be dictated in the brief \u2014 after which the test grades correctness, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue plus the expected-behavior evidence pin down a determinate, checkable outcome: exact topic strings, exact message wording, the URL construction rule for design comments, the payload shape that must be recognized, and the custom-topic prefix behavior. Concrete input/output examples are included so two independent implementations would be compatible."
}
