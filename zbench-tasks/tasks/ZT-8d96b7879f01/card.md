# ZT-8d96b7879f01 -- keyboard_UI: Allow use of `e` hotkey for spectators.

- lang: web   issue: #33838   tier: B
- fix: https://github.com/zulip/zulip/commit/8d96b7879f0196e3c895ef5af6720129d9f05729
- f2p: web/tests/hotkey.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix",
  "reason": "Real bug fix with an observable behavioral outcome: the 'e' (edit_message) hotkey should not trigger the login prompt for spectators. The hidden test grades behavior deterministically \u2014 it simulates the keydown as a spectator and asserts login_to_access is not called \u2014 rather than pinning exact output strings or snapshots. Fails before the fix, passes after."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "Every surface the test touches exists at the base commit. It imports the pre-existing public export `process_keydown` from `web/src/hotkey.js`, sets the long-standing `page_params.is_spectator` flag, and stubs `spectators.login_to_access` \u2014 a module and function that already exist pre-fix (the code diff shows the fix merely adds an entry to an allowlist that already gates calls to `spectators.login_to_access()`). The assertion itself is purely behavioral: pressing the 'e' key as a spectator must not route to the login-to-access prompt. Notably, the test does not bind to the new allowlist entry name `edit_message` or any other name the fix introduces, so a solver could pass it with any implementation that lets spectators' 'e' keypress through without triggering the login gate."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the observable bug (E shows a login modal for anonymous users despite the equivalent menu action working), and the evidence confirms the checkable outcome: with is_spectator true, processing an 'e' keydown must not invoke spectators.login_to_access and must proceed to the normal shortcut handling. This is a determinate, verifiable behavior change."
}
