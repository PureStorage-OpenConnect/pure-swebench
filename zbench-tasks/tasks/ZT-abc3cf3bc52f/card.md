# ZT-abc3cf3bc52f -- lightbox: Open YouTube videos at correct timestamp.

- lang: web   issue: #36990   tier: B
- fix: https://github.com/zulip/zulip/commit/abc3cf3bc52f44557bd27d31371ad62ce704dd91
- f2p: web/tests/util.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real, plausibly-assigned bug fix (YouTube lightbox ignores timestamp) with observable behavior change. The hidden test grades the new parse_youtube_start_time utility on deterministic input/output pairs (URL string \u2192 seconds or undefined), asserting behavior rather than snapshots or exact long output strings. It fails before the change (function doesn't exist / timestamp ignored) and passes after, with no time/version gating or formatting brittleness."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "The web/src/util module exports a function `parse_youtube_start_time(url: string): number | undefined` that extracts the start-time offset from a YouTube URL (both youtu.be short links and youtube.com/watch links).",
    "The function reads the `t` query parameter, falling back to the `start` query parameter if `t` is absent.",
    "A plain integer value (e.g. `t=120`) is returned as that number of seconds.",
    "A duration-formatted value of the form `#h#m#s` with each component optional (e.g. `1h1m1s`, `1h30m`, `1m`) is converted to total seconds (e.g. 3661, 5400, 60).",
    "If the URL has neither parameter, or the value matches neither the integer nor the duration format (e.g. `t=invalid`), the function returns `undefined`."
  ],
  "reason": "The test binds to one new name: an exported utility function on the pre-existing web/src/util module, exercised purely through its input/output behavior (URL string in, seconds or undefined out). A ticket could legitimately dictate this function's name, location, and parsing semantics \u2014 including the t/start fallback, the #h#m#s grammar, and the undefined sentinel \u2014 since the whole point of the feature is converting YouTube's string time offsets to integer seconds for the embed API. No mocks of internals, no private helper names, no internal data-structure layout are asserted; given the contract above, the test grades correctness rather than name-guessing."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the user-visible defect, and the expected-behavior evidence plus interface requirements pin down the exact parsing contract (parameter precedence, both URL forms, integer and #h#m#s duration formats, undefined on invalid input), making the outcome determinate and checkable."
}
