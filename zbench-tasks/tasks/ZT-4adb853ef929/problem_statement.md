# Display language names as autonyms in the language picker

## Background

Zulip's web app lets users pick their display language from a list (the language selection modal in settings). Each entry shows the language's name plus, for languages that are not fully translated, a translation-completeness percentage, e.g. `British English (99%)`.

Today, the names shown come from a server-provided list (`page_params.language_list` / the `language_list` passed to the web app's i18n module), and those names are inconsistent: some are written in the language itself (autonyms such as தமிழ், 日本語), while others are English names (e.g. "Hindi", "Malayalam", "Mongolian", "Bahasa Indonesia"). The goal is for every language in the picker to be displayed in that language itself.

Rather than hand-curating the remaining names, the picker should compute each language's autonym on the client from its language code.

## Required behavior

Change the web client's i18n language-list code (the module in `web/src` that exposes `get_language_list_columns`, which builds the list rendered by the language picker) so that the display name of each language is derived from its locale/language code instead of taken from the server-provided English `name` field:

1. **Autonym via `Intl.DisplayNames`.** For each language entry, use `Intl.DisplayNames` with the language's own locale (type `"language"`) to obtain the language's name in that language. The first character of the resulting name must be uppercased according to that locale (some locales return lowercase names, e.g. `id` yields "indonesia" and must display as `Indonesia`; `mn` should render as `Монгол`).

2. **Script subtags.** If the language code contains a script subtag (e.g. `zh-hans`, locale `zh_Hans`), the base language autonym is shown followed by the script's display name — localized in that same language — in parentheses. Example: `zh-hans` → `中文 (简体)`.

3. **Region subtags.** If the language code contains a region subtag (e.g. `en-gb`), the base language autonym is shown followed by the region's display name — localized in that same language — in parentheses. Example: `en-gb` → `English (United Kingdom)`.

4. **Special case for `en`.** The plain code `en` refers to US English and must be displayed as `English (United States)` (i.e. treat it as `en-US` for display purposes).

5. **Hardcoded exceptions.** For language codes where `Intl.DisplayNames` returns an English name rather than an autonym in some browsers, the implementation must carry fixed override names. At minimum: `bqi` must display as `Bakhtiari`, and `mn` must display as `Монгол`.

6. **Percentage suffix unchanged.** The existing formatting around the name is preserved: when an entry has a defined `percent_translated`, the rendered label is `<display name> (<NN>%)`; the fully translated default language shows just the display name with no percentage. The `selected` flag and `code` fields in each rendered entry keep their current semantics.

Note that language codes in the list use hyphenated lowercase forms (e.g. `zh-hans`, `en-gb`) while the `locale` field uses underscore forms (e.g. `zh_Hans`); the display-name computation must handle the codes as they appear in the list (BCP 47 hyphenated form works with `Intl.DisplayNames`).

## Interface requirements

- The language-picker list produced by the existing `get_language_list_columns` function must show each language's name in that language itself (its autonym), computed from the language code via `Intl.DisplayNames`, instead of the server-provided English name; the first character is uppercased according to the locale (e.g. `id` → `Indonesia`, `mn` → `Монгол`).
- If the language code contains a script subtag, the script's localized display name is appended in parentheses (e.g. `zh-hans` → `中文 (简体)`).
- If the language code contains a region subtag, the region's localized display name is appended in parentheses (e.g. `en-gb` → `English (United Kingdom)`).
- The code `en` must be displayed as US English, i.e. rendered as `English (United States)`.
- The languages `bqi` and `mn` must display the fixed names `Bakhtiari` and `Монгол` respectively, because `Intl.DisplayNames` returns English names for them in some browsers.
- The existing translation-percentage suffix format is preserved: the display name is followed by ` (NN%)` when `percent_translated` is defined, and omitted for the fully translated default language.

## Concrete examples

Given a language list containing entries with codes `en` (default, fully translated), `en-gb` (99%), `id` (32%), `mn` (53%), `bqi` (5%), and `zh-hans` (86%), the picker must render:

- `en` → `English (United States)`
- `en-gb` → `English (United Kingdom) (99%)`
- `id` → `Indonesia (32%)`
- `mn` → `Монгол (53%)`
- `bqi` → `Bakhtiari (5%)`
- `zh-hans` → `中文 (简体) (86%)`
