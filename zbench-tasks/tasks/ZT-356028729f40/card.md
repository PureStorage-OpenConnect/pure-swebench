# ZT-356028729f40 -- thumbnails: Handle dinky thumbnail images.

- lang: web   issue: #31502   tier: B
- fix: https://github.com/zulip/zulip/commit/356028729f4009f33a6d5d3abd2e7c3952173d4a
- f2p: web/tests/postprocess_content.test.cjs
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "bug fix (frontend behavior)",
  "reason": "Real, plausibly-assigned fix: small ('dinky') images get a dedicated CSS class so they aren't rendered in the oversized grey thumbnail box. The change is observable and deterministic \u2014 postprocess_content is a pure string-transform function, and asserting its output HTML for a targeted input is the natural way to grade it, not a brittle snapshot: the asserted string is a short, single-element fixture whose content (the added dinky-thumbnail class, computed from data-original-dimensions vs. web_font_size_px) is exactly the behavior the commit changes. The test fails before the fix and passes after, with no time/version gating, no i18n or docs churn, and no dependence on incidental or non-deterministic formatting."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "Images in message content whose original dimensions (taken from the existing `data-original-dimensions` attribute, in pixels) are both less than or equal to the 10em thumbnail box at the user's configured font size (10 \u00d7 the existing `web_font_size_px` user setting; comparison is inclusive) are considered 'dinky' thumbnails.",
    "The rendered `<img>` element for a dinky thumbnail gains the CSS class `dinky-thumbnail`, in addition to the existing orientation class (`portrait-thumbnail`/`landscape-thumbnail`) and other pre-existing attributes (width/height from original dimensions, lazy loading).",
    "Dinky thumbnails must be served at the smallest thumbnail resolution: the image `src` uses the `300x200.webp` thumbnail variant of the upload instead of the default `840x560.webp` variant."
  ],
  "reason": "The test drives the pre-existing public entry point postprocess_content(html) and asserts only the user-visible transformed HTML; it stubs no new internal helpers. The user setting web_font_size_px already exists at the base commit (information-density settings), so populating it is not new surface. The only new bindings are the CSS class name `dinky-thumbnail` on the img element, the inclusive 10em-box threshold semantics relative to the user's font size (1x10 at 16px font qualifies), and the choice of the small 300x200 thumbnail variant in the src URL \u2014 all DOM/output contract a ticket or design spec would legitimately pin. Handed these requirements, a solver is graded on correct behavior, not on guessing the author's private naming."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue supplies the product intent (remove grey box, keep a padded click target for tiny images) and the expected-behavior evidence plus interface requirements pin down the checkable client-side contract exactly: the dinky threshold (both dimensions \u2264 10 \u00d7 web_font_size_px, inclusive), the added `dinky-thumbnail` class alongside existing orientation class and attributes, and the src rewrite from the 840x560.webp variant to 300x200.webp. A worked input/output example makes independent implementations compatible."
}
