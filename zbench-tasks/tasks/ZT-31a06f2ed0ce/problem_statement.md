## Guarantee that every `Integration` has a resolvable logo

### Background / current behavior

In `zerver/lib/integrations.py`, the `Integration` class resolves a logo during construction:

```python
self.logo_path = logo if logo is not None else self.get_logo_path()
# TODO: Enforce that all integrations have logo_url with an assertion.
self.logo_url = self.get_logo_url()
```

Today `get_logo_path()` returns `Optional[str]`: it looks for the integration's default SVG logo file and then its default PNG logo file on disk, and returns `None` if neither exists. Consequently `logo_path` and `logo_url` are also `Optional[str]`, and it is possible to construct an `Integration` that has no logo at all. Most integrations do have logo files under `static/images/integrations/logos/` (or, for bot integrations, under the generated-bots logo path such as `generated/bots/xkcd/logo.png`), but the embedded bot integrations (`converter`, `encrypt`, `helloworld`, `virtual_fs`, `giphy`, `followup` in `EMBEDDED_BOTS`) have no per-bot logo files, so their `logo_url` is `None`.

### Required behavior

Every `Integration` instance must end up with a real, non-`None` logo — `logo_path`/`logo_url` should be guaranteed strings, not optionals — and this must be enforced with assertions rather than silently allowing `None`.

1. **Logo resolution.** `Integration.get_logo_path` must return a definite path (type `str`, never `None`). It checks, in order: the integration's default SVG logo path, then its default PNG logo path (each subclass keeps its own default locations — e.g. plain/webhook integrations under `images/integrations/logos/<name>.(svg|png)`, bot integrations under the `generated/bots/<name>/logo.(svg|png)` scheme), then an optional caller-supplied fallback path. It returns the first of these that corresponds to a file that actually exists on disk.
2. **Failure is an error, not `None`.** If none of the checked paths exist on disk, `get_logo_path` must raise `AssertionError` instead of returning `None`. This applies both when no fallback is supplied and when the supplied fallback also does not exist. Examples with the current tree: calling `get_logo_path()` (no fallback) on the `slack_incoming` integration must raise `AssertionError`, because that integration is configured with an explicit `logo` argument precisely because it has no file at its default logo paths; likewise calling it with no fallback on an embedded bot such as `converter` must raise `AssertionError`. In contrast, `onyx` (which has only a PNG logo file) resolves to `images/integrations/logos/onyx.png`, and the `xkcd` bot integration resolves to `generated/bots/xkcd/logo.png`.
3. **Construction-time enforcement.** Constructing an `Integration` whose logo cannot be resolved — no explicit `logo` argument passed and no default SVG/PNG logo file present on disk — must raise `AssertionError`. For example, `Integration("alertmanager", ["misc"])` (no `logo` argument; there is no `images/integrations/logos/alertmanager.*` file) must fail to construct. It must no longer be possible to create an integration object without a logo.
4. **Embedded bots keep working via a shared fallback.** The embedded bot integrations in `EMBEDDED_BOTS` have no per-bot logo files, yet module import (which constructs all of them) must continue to succeed. Achieve this by having the embedded-bot construction path resolve its logo with the Zulip icon as the fallback: the static path `images/logo/zulip-icon-128x128.png`. So `EMBEDDED_BOTS[0].get_logo_path("images/logo/zulip-icon-128x128.png")` yields `"images/logo/zulip-icon-128x128.png"`, while the same call without the fallback raises `AssertionError`. Do not bake this Zulip-icon fallback into `get_logo_path`'s default (no-argument) behavior — it is supplied explicitly where embedded bots resolve their logo at construction time.

Existing helpers that build on the logo path (such as `get_logo_url` and `get_bot_avatar_path`) should be updated consistently with the new non-optional guarantee: since construction now fails when no logo resolves, these no longer need to handle a missing logo by returning `None`.

### Interface requirements

- `Integration.get_logo_path` gains an optional parameter `fallback_logo_path: str | None = None` and now returns `str` (never `None`): it returns the first path that exists on disk among the integration's default SVG logo path, its default PNG logo path, and then the `fallback_logo_path` argument if one was provided.
- `Integration.get_logo_path` raises `AssertionError` (instead of returning `None`) when none of the checked logo paths exist — including when called with no fallback argument on an integration whose default logo files are absent (e.g. embedded bots, or an integration that was given an explicit `logo` argument because it has no file at its default paths).
- Constructing an `Integration` whose logo cannot be resolved (no explicit `logo` argument and no default SVG/PNG logo file on disk) raises `AssertionError`; integrations may no longer exist without a logo.
- Embedded bot integrations must construct successfully despite having no per-bot logo files, by falling back to the Zulip icon at static path `images/logo/zulip-icon-128x128.png`; this fallback is applied when resolving the logo at construction time, not baked into `get_logo_path`'s no-argument behavior.
