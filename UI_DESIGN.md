# Dashboard design system

> Plane: INTERNAL_RUNBOOK. Currency: CURRENT. Owner: dashboard-ui. Current-number policy: none.

The **single discoverable owner** of the report dashboard's UI conventions. The code SoT
is the `UI DESIGN SYSTEM` header + registries in `tools/bench_dashboard.py` (one file,
server-rendered + inline-SVG, no build step); this doc states the principles and points at
the enforcement; this doc is the concrete "how" for the dashboard.

## Principles (the target)

1. **No frameworks, no build step.** One vanilla server + inline-SVG; a data-only API
   (`/api/*` JSON) with the view rendered client-side in hand-rolled JS. Ship data, not fat
   HTML. Minimize DOM nesting (the nav is dead-stable at the top level, not another wrapper).
2. **One icon language.** All iconography = Material Design Icons via a single inline-SVG
   registry — server `icon("name")` + client `mdi("name")` off the same `MDI` path table
   (injected as `_ICON_JS`). No emoji, geometric chars (`▲▼●·`), or HTML-entity glyphs
   (`☠⚠⊘⚙✓↻⬇`) used *as icons*. Text and numbers stay text.
3. **One meaning → one icon + one color.** A semantic (running, waiting, contamination,
   artifact, clean, excluded/muted) maps to exactly one glyph+hue everywhere, from one token
   table (`OUTCOME`/`PALETTE`; issue-type chips are `TYPEC` = bug/feature/other), never
   inline. An icon must not merely duplicate a background color.
4. **One style + token layer.** One CSS source with design tokens (`PALETTE` → `:root`
   `var(--*)`) and a small shared component set (badge, chip, pill, button); no per-call
   inline hex.
5. **One edit paradigm, stated.** Editable *text* (notes, exclusion reason) = click-to-edit
   inline (span -> reveal form -> save on blur/Enter), via the shared `_NOTE_EDIT_JS`.
   *Actions* (copy, download, toggle) = a button/icon-button. Rows are uniform -- a new
   note is just the empty last row, no special "add" affordance.
6. **One "open/link" affordance.** One link style means "go to detail"; reserve directional
   arrows for genuine flow only (pager, `in→out`, pipeline stages), never as link decoration.
   A task reference is the bare id linked to the canonical task page (not the upstream
   GitHub issue/commit — those live on the task page), via the shared task-link helper.
7. **One text-encoding convention.** Server-rendered HTML *text* uses HTML entities (or a
   helper); never raw `\uXXXX` in a Python string destined for HTML text (that is what broke
   W62/W92). Keep `\u` only inside real JS string literals.
8. **Shared scaffolds, deduped.** One sortable/filterable table scaffold
   (`sortableThs`/`filterSort`), one `el()`, one nav, one notes machinery — each page supplies
   only its columns/renderers. Deduplicate only genuinely-same concerns; keep intrinsically-
   different renderers separate (don't force-share look-alikes).
9. **Minimal surfaced text; drill-down; show reality.** Captions default to nothing (short
   non-obvious caveats only; longer notes behind `<details>`). Every number links to the rows
   behind it. Present the real N executions and rank at the finest honest grain
   (model×harness); excluded rows stay visible, struck-through + muted.
10. **Status is ONE value, from a real state machine — not presentation-layer conditionals.**
    Don't collapse `state` + `failure-mode` + outcome by ad-hoc branching in the renderer;
    model one lifecycle status (a state machine with a terminal state per failure mode) and
    show the path through it in the detail view. (Data-vs-presentation: derive status in the
    domain layer, render it in the view.)
11. **One shared nav on every page; no reinvented breadcrumbs.** Every page carries the same
    top nav (return to any section). The current page is "this" — unlinked; never smuggle
    extra info (a `batch run ↗` / `card ↗`) into a breadcrumb line.
12. **Show a datum once; put the link on the meaningful element.** No redundant repetition
    (recognize a leading task id and link it once, not three times). Link the relevant
    element itself (status → detail; a leading log/scroll icon → live) and drop filler
    link-words ("view"/"run"/"detail") and columns that add nothing (e.g. a derivable `try`).
13. **Leading, aligned icons.** A card/download/action icon sits at the FRONT of its value in a
    fixed-width reserved slot so icons align vertically across rows — never a trailing
    superscript; per-row action buttons align (button before status, not after).
14. **Reuse over reinvent.** Prefer borrowing/importing an existing renderer (e.g. pi's
    transcript viewer, taken as a source dependency) or the shared scaffold over hand-rolling
    (see §8/dedup).
15. **One topic per view.** Heavy pages are split into focused tabs (Leaderboard / Runs /
    Corpus / Agents) to lower per-view cognitive load and drive modular implementation — a tab
    lands on its topic, no long scroll.
16. **Precise labels.** Every label/status answers "of what?" — no bare "valid"/"invalid"
    (validity of a *run*? a *note*?); prefer "exclude/disregard" over "invalidate".

## Enforcement

`tools/consistency_check.py`:
- `check_dashboard_icons` — no emoji/entity/geometric glyphs as icons (banned-entity +
  banned-char lists); verified to fire on an injected glyph.
- `check_token_backfill`, `check_doc_code_refs`, etc. guard other invariants.

## Status (from the recovered review; keep current)

Implemented: U1 palette tokens · U2 MDI registry (all pages) · U3 CSS tokens (core) · U4
shared button + badge/chip components · U5 shared edit-JS · U6 open-detail/link convention
(arrows reserved for real flow/navigation) · U7 icon lint · U8 no auto-refresh · the
data-only API + client-render split · the shared table scaffold + task-link + caption trims.
W70 completed 2026-08-05 after operator visual approval of the current style: consolidation
only, no surprise restyle.
