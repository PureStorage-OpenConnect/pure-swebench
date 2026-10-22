# ZT-14173b757f93 -- github webhook: Support all actions on discussion events.

- lang: py   issue: #26064   tier: B
- fix: https://github.com/zulip/zulip/commit/14173b757f9377cae7b5c8113b1e92b02f5b62a7
- f2p: zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_answered, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_category_changed, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_category_changed_with_custom_topic_in_url, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_closed, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_created, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_deleted, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_edited_body, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_edited_title, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_labeled, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_locked, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_pinned, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_reopened, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_transferred, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_unanswered, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_unlabeled, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_unlocked, zerver.webhooks.github.tests.GitHubWebhookTest.test_discussion_unpinned
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, well-scoped engineering task: the GitHub webhook incorrectly rendered every discussion action as 'created', and the fix adds per-action message handling. The hidden test grades observable outcome deterministically \u2014 it feeds recorded webhook fixture payloads for each action and asserts the resulting Zulip message. While Zulip webhook tests do compare exact message strings, those strings ARE the observable behavior being fixed (short, deterministic, per-action notification text), not incidental formatting or a long snapshot; a fail-before/pass-after signal exists for every new action. Not in any drop category."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The GitHub webhook integration must handle all `discussion` event actions (not just `created`), producing Zulip messages via the pre-existing webhook endpoint; topic naming keeps the existing '{repo} discussion #{number}: {title}' format.",
    "For action 'created', the message is: '{sender} created [discussion #{number}]({html_url}) in {category name}:' followed by a Zulip quote block containing '### {title}' and the discussion body (this matches the pre-existing created-message format except the numbered link now reads 'discussion #{number}').",
    "For actions 'unlocked', 'pinned', 'unpinned', and 'reopened', the message is: '{sender} {action} [discussion #{number}{optional title}]({html_url}).' where the action verb is the raw payload action.",
    "For action 'deleted', the message is: '{sender} deleted discussion #{number}{optional title}.' with no hyperlink (the discussion no longer exists).",
    "For action 'closed', the message is: '{sender} closed [discussion #{number}{optional title}]({html_url}) as {state_reason}.' using the payload's discussion state_reason (e.g. 'resolved').",
    "For action 'locked', the message is: '{sender} locked [discussion #{number}{optional title}]({html_url}{optional title}) as {active_lock_reason}.'; when active_lock_reason is null the entire ' as {reason}' suffix is omitted.",
    "For actions 'labeled'/'unlabeled', the messages are: '{sender} added the {label name} label to [discussion #{number}{optional title}]({html_url}).' and '{sender} removed the {label name} label from [discussion #{number}{optional title}]({html_url}).'",
    "For action 'category_changed', the message is: '{sender} changed the category of [discussion #{number}{optional title}]({html_url}) from {old category name} to {new category name}.'",
    "For action 'transferred', the message is: '{sender} transferred discussion #{old number}{optional title} from {old repository name} to {new repository name} as [discussion #{new number}]({html_url}).' reading the new repository and new discussion number from the payload's 'changes' object.",
    "For action 'answered', the message is: '{sender} marked [comment #{answer comment id}]({answer html_url}) as the answer:' followed by a quote block with the answer comment's body; for 'unanswered', the message is '{sender} marked [comment #{old_answer comment id}]({old_answer html_url}) as not the answer.' (answered reads the 'answer' payload field, unanswered reads 'old_answer').",
    "For action 'edited': if the payload's 'changes' object contains 'body', the message is '{sender} edited [discussion #{number}{optional title}]({html_url}):' followed by a quote block with the new body; otherwise (title edit) it is '{sender} edited the title of [discussion #{number}{optional title}]({html_url}):' followed by a quote block with '### {new title}'.",
    "'{optional title}' means: when the integration's pre-existing include-title configuration (topic in URL query) is enabled, the discussion title is appended after the number as ' {title}' inside the link text; otherwise it is omitted.",
    "'{sender}' uses the integration's pre-existing sender-name formatting (the payload sender's login)."
  ],
  "reason": "The hidden test exercises the pre-existing GitHub webhook endpoint with new discussion-event fixtures and asserts the resulting user-visible Zulip message strings and topics. It does not bind to any internal names the fix invents (DISCUSSION_TEMPLATES, LazyContext, get_discussion_action are never referenced directly \u2014 the test goes through the HTTP interface). The only new surface is the exact wording of the bot messages per discussion action, which is user-facing output that a ticket would legitimately pin verbatim (Zulip integration tickets routinely specify exact message formats). With the message contract above in the brief, the test grades correctness of payload handling, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue identifies the defect (the discussion handler always renders a 'created' message regardless of action), and the interface requirements plus behavior evidence pin down the exact per-action message formats, payload fields to read, link/no-link rules, and edge cases (null active_lock_reason, body-vs-title edits, deleted having no link). This is enough for two engineers to independently produce compatible implementations."
}
