# Modernize Zulip's exception-report filtering and stop leaking Django settings in production error reports

## Background

Zulip customizes how Django scrubs sensitive data out of exception reports (the tracebacks that appear in error emails and the debug error page). This customization lives in `zerver/filters.py`, in a filter class that predates the modern extension points on Django's `django.views.debug.SafeExceptionReporterFilter` (such as the `cleansed_substitute` and `hidden_settings` attributes). The code should be cleaned up to build on those modern hooks where they help.

Separately, there is a real data-exposure problem: when an exception occurs on a production server, the report Django generates includes a dump of the Django settings. Even with individual values scrubbed, a production Zulip server's error emails should not include the settings dump at all. In a development environment, however, the settings dump is genuinely useful for debugging and must remain.

## Required behavior

All of the following describes the class `ZulipExceptionReporterFilter`, importable from `zerver.filters`. It must be a working exception reporter filter compatible with Django's `django.views.debug.ExceptionReporter` (i.e., usable as the reporter's `filter`), and it should remain the filter Zulip's settings configure for exception reporting.

### 1. Masking of sensitive POST parameters

When the filter processes the POST parameters of a request (via the standard `get_post_parameters(request)` hook), the following parameter names must have their values replaced by the exact string `**********` (ten asterisks):

- `password`
- `api_key`
- `content`
- `realm_counts`
- `installation_counts`

Any other POST parameter (for example, an arbitrary field like `normal_field`) must pass through with its value unchanged. This matches the historical behavior of the existing filter — take care not to change the substitute string or the set of masked keys while refactoring. (The full historical list in `zerver/filters.py` also includes secrets such as OTP fields and API secrets; preserve the existing set, of which the names above are the essential members.)

### 2. Django settings must be omitted from production exception reports

When Zulip is running in production (i.e., the Django setting `PRODUCTION` is true), an `ExceptionReporter` using this filter must produce traceback data whose `settings` entry is an **empty dict** (`{}`) — not a scrubbed copy, but empty. Consequently, the rendered traceback HTML for a production exception must not contain any settings content: names like `LANGUAGE_CODE`, `SECRET_KEY`, or `DATABASES` must not appear anywhere in the HTML output.

This must hold for reports generated for email (`is_email=True`), since error emails are the primary way these reports leave the server.

### 3. Settings must still appear in development

When not running in production, the same reporter/filter combination must still include settings in the traceback data: the `settings` entry must be present and be a non-empty dict, so developers keep the full debugging context.

## Notes

- The production/development distinction is Zulip's own `PRODUCTION` setting, not Django's `DEBUG`.
- Prefer implementing this by overriding the appropriate modern `SafeExceptionReporterFilter` hooks rather than reimplementing Django internals; where the modern attributes (`cleansed_substitute`, `hidden_settings`) simplify the existing code without changing the observable behavior above, use them.
- Behavior must be deterministic regardless of deployment paths (e.g., a production `DEPLOY_ROOT` like `/home/zulip/deployments/<timestamp>`).

## Acceptance criteria

1. `from zerver.filters import ZulipExceptionReporterFilter` works, and `ZulipExceptionReporterFilter().get_post_parameters(request)` on a POST containing the five parameter names listed above returns each of them mapped to `**********` while unrelated parameters are unchanged.
2. With `PRODUCTION=True`, an `ExceptionReporter` (with `is_email=True`) whose filter is `ZulipExceptionReporterFilter` returns traceback data with `settings == {}`, and its traceback HTML contains none of `LANGUAGE_CODE`, `SECRET_KEY`, `DATABASES`.
3. Without `PRODUCTION`, the same reporter returns traceback data where `settings` is a non-empty dict.
