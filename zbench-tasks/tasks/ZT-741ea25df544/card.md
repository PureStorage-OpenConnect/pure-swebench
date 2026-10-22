# ZT-741ea25df544 -- exception-reporter: Add ZulipExceptionReporterFilter with POST masking and settings removal.

- lang: py   issue: #36706   tier: B
- fix: https://github.com/zulip/zulip/commit/741ea25df5449dc4f368191bd1e9dcbf5e3fd68e
- f2p: zerver.tests.test_exception_filter.TestExceptionFilter.test_exception_reporter_omits_settings_in_production, zerver.tests.test_exception_filter.TestExceptionFilter.test_exception_reporter_returns_settings_in_dev, zerver.tests.test_exception_filter.TestExceptionFilter.test_zulip_filter_masks_sensitive_post_data
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior-affecting refactor (security hardening of exception reports)",
  "reason": "Real engineering workflow (cleaning up SafeExceptionReporterFilter usage while hardening exception reports) with a genuine observable behavior change: in production, Django settings are omitted from exception reports entirely, while dev keeps masked settings. The hidden test grades outcomes deterministically \u2014 masked POST parameters, settings dict empty vs. non-empty via ExceptionReporter.get_traceback_data(), and absence of specific setting names (SECRET_KEY, DATABASES) in the traceback HTML. It fails before the change and passes after, and it asserts targeted substrings/values rather than pinning a full HTML/JSON snapshot, so it is not format-brittle. The '**********' mask assertion matches the code's specified masking contract, not incidental formatting."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "Every name the test binds to already exists at the base commit. `zerver.filters.ZulipExceptionReporterFilter` and its POST-parameter masking (the filtered field list and the '**********' mask) pre-exist \u2014 the code diff only refactors that method's internals, and the first test exercises pre-existing behavior. The new behavior (omitting Django settings from exception reports in production, keeping them in development) is verified entirely through pre-existing interfaces: Django's public `ExceptionReporter.get_traceback_data()`/`get_traceback_html()` and its 'settings' key, and Zulip's pre-existing `PRODUCTION` setting. The test never names the new `get_safe_settings` override directly; that hook is Django's framework-dictated extension point, not an author-invented internal. A solver given only the behavioral requirement would produce code this test grades on correctness, with no name-guessing required."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the goal (modernize zerver/filters.py using SafeExceptionReporterFilter features and, ideally, disable settings inclusion in production error emails), and the expected-behavior evidence pins down concrete, checkable outcomes: the class name and module, the exact mask string and masked POST parameter names, settings present and non-empty outside production, and settings empty (and absent from HTML) when PRODUCTION=True. Together these are sufficient for two engineers to build compatible implementations."
}
