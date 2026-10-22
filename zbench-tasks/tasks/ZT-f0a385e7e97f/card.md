# ZT-f0a385e7e97f -- integrations: Rebrand Clubhouse webhook integration to Shortcut.

- lang: py   issue: #22731   tier: B
- fix: https://github.com/zulip/zulip/commit/f0a385e7e97fb3101742ac251e3de46290da0381
- f2p: zerver.webhooks.shortcut.tests.ShortcutWebhookTest.test_legacy_urls, zerver.webhooks.shortcut.tests.ShortcutWebhookTest.test_story_create
- p2p: zerver.tests.test_integrations

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior-affecting refactor (integration rebrand with endpoint rename + legacy alias)",
  "reason": "Not a pure no-behavior rename: the webhook gains a new URL endpoint (api_shortcut_webhook / /api/v1/external/shortcut), the integration registry entry changes name/category registration, and legacy_names=['clubhouse'] must keep the old endpoint working. A hidden test can deterministically fail-before/pass-after by POSTing fixtures to the new endpoint, checking the integration catalog exposes 'shortcut', and verifying the legacy 'clubhouse' URL still routes. The test diff is standard Zulip webhook fixture testing (fixture files + expected message checks), not a fragile whole-output snapshot; fixture/directory naming is fully specified by the commit subject and issue title, so the grader tests the specified observable outcome rather than incidental formatting."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The incoming webhook integration previously named `clubhouse` is renamed to `shortcut` (Clubhouse the product rebranded to Shortcut), so its integration name/slug registered in INCOMING_WEBHOOK_INTEGRATIONS is `shortcut` under the `project-management` category",
    "The webhook is served at the URL endpoint `/api/v1/external/shortcut` (the endpoint name derived from the integration slug per Zulip's incoming-webhook framework convention)",
    "Per Zulip's webhook framework convention that endpoint names map to `zerver/webhooks/<name>/view.py` exposing `api_<name>_webhook`, the handler lives at `zerver.webhooks.shortcut.view.api_shortcut_webhook`",
    "The old integration name `clubhouse` is retained as a legacy alias so existing webhook URLs using `/api/v1/external/clubhouse` continue to work and route to the same handler",
    "User-visible bot message content is unchanged in structure; only the product branding follows the payload (fixtures now carry app.shortcut.com URLs), so messages must render the URLs/names supplied in the payload rather than hardcoding the old clubhouse.io domain"
  ],
  "reason": "This is a product-rename task (Clubhouse \u2192 Shortcut). The test binds to new names \u2014 the `shortcut` endpoint/module/handler and the `clubhouse` legacy alias \u2014 but all of them are exactly what a rename ticket would dictate, plus names mechanically derived from the slug by Zulip's existing webhook framework convention (directory `zerver/webhooks/<name>`, function `api_<name>_webhook`). Fixture files and their contents are supplied by the test itself, so the solver doesn't guess payload data. Nothing binds to private helpers or internal structure the fix invents; even if the reference fix adds a `legacy_names` mechanism internally, the test-observable behavior is the legacy URL continuing to work, which the contract states. With these requirements in the brief, the test grades correctness of the rename, not name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the rebrand goal, the expected-behavior evidence pins down the module rename (zerver/webhooks/clubhouse \u2192 zerver/webhooks/shortcut) and that payload URLs move to app.shortcut.com, and the interface requirements specify the exact registry slug, endpoint, handler name, and the legacy-alias requirement. Together these give a determinate, checkable outcome: endpoint names, handler location, alias behavior, and message-content invariants are all specified."
}
