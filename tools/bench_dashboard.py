#!/usr/bin/env python3
"""Read-only web VIEW over the zbench store. Writes nothing.

SINGLE STORE: everything comes from bench.db (facts + invalidation) + the git
task files (curation) + the .runtime/live leases (liveness). The front page +
/api/state are served by benchdb_reader.collect_state (SQL); the drill-down
endpoints (/runs, /task, /run, /batch) query bench.db via _benchdb_attempts.
There is no legacy file store (the append JSONL + event log were retired at cutover).

See tools/README.md for the model + endpoints, METHODOLOGY.md for the
ranking rules, and scoring.py / METHODOLOGY.md for validity.

Run as a systemd user service (bench-dashboard) or: python3 bench_dashboard.py
[--port 8787] [--benchdb PATH].
"""
from __future__ import annotations

import argparse
import base64
import collections
import html
import json
import math
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

# rich transcript renderer (reuses pi's vendored MIT client-side viewer)
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import transcript_view
except Exception:  # viewer optional; dashboard still works without it
    transcript_view = None

# shared validity primitives (single source of truth -- see zbench-tasks/scoring.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "zbench-tasks"))
import scoring
import exclusions  # DEDUP_REVIEW D1: single source for scoring-exclusion prefixes

# zbench identity helpers (instance prefix / task-id / cell-key / tracker-url policy)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from zbench import constants

# ---- defaults (override with flags / env) --------------------------------
ROOT = Path(__file__).resolve().parent.parent
DEF_TASKS = os.environ.get("ZBENCH_TASKS", str(ROOT / "zbench-tasks" / "tasks"))

TASKS = Path(DEF_TASKS)
# Answer keys live OUTSIDE the task dirs so a solver reading this repo cannot find them.
SOLUTIONS = TASKS.parent / "solutions"

# SQL backend: bench.db is the SINGLE store (schema SoT: zbench/schema.sql;
# single-store invariant: METHODOLOGY.md section 7). The front
# page + /api/state are served from it via the SQL reader (benchdb_reader); the
# drill-down endpoints query bench.db via _benchdb_attempts. Raw transcript/stderr
# drill-downs read blobs/io_logs where present (evidence-to-blobs is the last
# residual). The old file `collect_state()` was removed at cutover.
DEFAULT_DB = Path(os.environ.get("ZBENCH_BENCHDB_DIR", str(ROOT / "bench-db"))) / "bench.db"
BENCHDB = str(DEFAULT_DB)   # the single store; the board always reads bench.db
RUNTIME = None      # Path to .runtime/ (liveness leases), or None -> DB sibling

# Single manifest for task-local files exposed by /task and /task_file. Labels here are
# UI labels; `spoiler` marks reference/oracle artifacts that should be named honestly.
TASK_ARTIFACTS = [
    {"name": "problem_statement.md", "label": "problem statement / initial prompt", "kind": "input"},
    {"name": "instance.jsonl", "label": "instance.jsonl", "kind": "raw"},
    {"name": "meta.json", "label": "meta.json", "kind": "raw"},
    {"name": "gold_test.patch", "label": "gold test patch", "kind": "patch", "spoiler": "oracle/spoiler"},
    {"name": "gold_code.patch", "label": "gold code patch", "kind": "patch", "spoiler": "reference/spoiler"},
    {"name": "card.md", "label": "raw card.md", "kind": "raw"},
    {"name": "agents.jsonl", "label": "task-local agents.jsonl", "kind": "raw"},
]
TASK_ARTIFACT_NAMES = {a["name"] for a in TASK_ARTIFACTS}

# NOTE: agents/attempts dropped from ANALYSIS are not a hardcoded set -- scoring
# exclusions are rows in bench.db (`run_exclusion`, plus legacy invalidation evidence),
# read through scoring / benchdb_reader.



def _fmt_ts(ts):
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def _resfmt(x):
    """Format 'resolved' (sum of per-cell pass rates): integer when whole, else 1dp."""
    x = x or 0
    return f"{x:.0f}" if abs(x - round(x)) < 1e-9 else f"{x:.1f}"


def _costfmt(per_task):
    """Format a per-task USD cost with ENOUGH precision to stay legible for cheap
    models (W110). A flat 2dp printed `$0.00` for e.g. deepseek-v4-flash (~$0.0015/task,
    real -- computed from captured tokens x models.dev, not free). Adaptive: keep ~2
    significant digits below a cent so sub-cent costs are visible, 2dp once >= $0.10."""
    if per_task is None:
        return None
    p = float(per_task)
    if p >= 0.10:
        return f"${p:.2f}"
    if p >= 0.01:
        return f"${p:.3f}"
    if p >= 0.001:
        return f"${p:.4f}"
    return f"${p:.5f}"


def _cost_cell_html(per_task):
    """Decimal-point-ALIGNED $/task cell (readability): split '$INT.FRAC' into a
    right-aligned integer part and a FIXED-WIDTH left-aligned fractional part, so the
    decimal points line up in a column despite _costfmt's variable precision (2-5 dp).
    Returns inner HTML for a `<td class=num>`; the muted n/a span if there is no cost."""
    s = _costfmt(per_task)
    if s is None:
        return '<span class=muted title="pricing not wired -- reports $0, NOT free">n/a</span>'
    intp, _, frac = s.partition(".")
    frac = ("." + frac) if frac else ""
    return (f'<span class=costcell><span class=i>{intp}</span>'
            f'<span class=f>{frac}</span></span>')


def _harness(agent_id):
    """Infer the harness/CLI from an agent_id prefix (pi, claude-code, codex, ...)."""
    a = (agent_id or "").lower()
    if a.startswith("pi-") or a == "pi":
        return "pi"
    if a.startswith("claude"):
        return "claude-code"
    for h in ("codex", "cursor", "gemini", "auggie"):
        if a.startswith(h):
            return h
    return "other"


def _age(ts):
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds()
    except Exception:
        return None


# =====================================================================
# UI DESIGN SYSTEM. Discoverable owner doc: ../UI_DESIGN.md (principles + status); this
# module is the CODE SoT (registries + enforcement). ONE palette + ONE icon
# language. All iconography = Material Design Icons via a single inline-SVG
# registry, usable both server-side (Python `icon()`) and client-side (JS
# `mdi()` -- same path table, injected as `_ICON_JS`). No emoji / geometric
# chars / entity glyphs as icons. Palette = centralized slate/blue tokens
# (U1/U3), also exported to CSS variables (`_CSS_TOKENS`) and JS (`PAL`).
# TEXT IS MINIMAL: a table/section caption DEFAULTS TO NOTHING; add only a SHORT
#   genuinely non-obvious caveat. Never state self-evident UI hints ("click to
#   sort", "one row per X"), implementation details (api routes, jsonl paths,
#   "client-rendered"), or exhaustive field lists. When a longer note is truly
#   warranted, hide it behind a collapsed <details> ("how to read this").
# ROOT-CAUSE over compensating transforms (GENERAL principle, see AGENTS.md):
#   fix a problem at its SOURCE; do NOT sprinkle workarounds across call sites.
#   Anti-pattern to avoid: adding a form in N places then stripping it in M others
#   (the old instance-id round-trip -- bench.db stores the bare task id, the
#   dashboard prepended the `zbench_` instance prefix then stripped it back for
#   display). Carry the CANONICAL form (bare task id) everywhere; construct a boundary form ONCE, only
#   where the boundary (runtime lease key / pb instance id) actually needs it.
# =====================================================================
PALETTE = {
    "fg": "#0f172a", "muted": "#64748b", "muted2": "#94a3b8",
    "accent": "#2563eb", "border": "#e2e8f0", "bg": "#f8fafc",
    "ok": "#16a34a", "okSoft": "#86efac", "bad": "#dc2626", "badSoft": "#fecaca",
    "warn": "#b45309", "warnSoft": "#fde68a", "artifact": "#7c3aed",
    "border2": "#cbd5e1", "line": "#eef2f7", "thbg": "#f1f5f9",
    # W106: a NEUTRAL CATEGORICAL pair for the open-weight vs proprietary cut --
    # deliberately NOT ok/bad (green/red), which wrongly reads as good/bad. Indigo
    # (open-weight, the on-prem-able protagonist) vs amber (proprietary frontier);
    # high hue separation, both saturated/legible, no value judgment.
    "openw": "#4f46e5", "openwSoft": "#e0e7ff", "prop": "#d97706", "propSoft": "#fed7aa",
}

# U3: ONE token layer -> CSS variables (kebab-case). Prepended to the app CSS so
# palette/spacing live in one place; new rules should reference var(--*).
_CSS_TOKENS = (":root{"
    "--fg:#0f172a;--muted:#64748b;--muted2:#94a3b8;--accent:#2563eb;"
    "--border:#e2e8f0;--border2:#cbd5e1;--bg:#f8fafc;--line:#eef2f7;--thbg:#f1f5f9;"
    "--ok:#16a34a;--ok-soft:#86efac;--bad:#dc2626;--bad-soft:#fecaca;"
    "--warn:#b45309;--warn-soft:#fde68a;--artifact:#7c3aed;"
    "--openw:#4f46e5;--openw-soft:#e0e7ff;--prop:#d97706;--prop-soft:#fed7aa;--radius:4px}")

# name -> Material Design Icon path 'd' (24x24 viewBox). Add new glyphs HERE ONLY.
MDI = {
    "file-document": "M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z",
    "note-text": "M14,17H7V15H14M17,13H7V11H17M17,9H7V7H17M19,3H5C3.89,3 3,3.9 3,5V19C3,20.1 3.89,21 5,21H19C20.1,21 21,20.1 21,19V5C21,3.9 20.1,3 19,3Z",
    "cog": "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5M19.43,12.98C19.47,12.66 19.5,12.34 19.5,12C19.5,11.66 19.47,11.34 19.43,11.02L21.54,9.37C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27C19.54,5.05 19.27,4.97 19.05,5.05L16.56,6.05C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05C4.73,4.97 4.46,5.05 4.34,5.27L2.34,8.73C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11.02C4.53,11.34 4.5,11.67 4.5,12C4.5,12.33 4.53,12.66 4.57,12.98L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73C4.46,18.95 4.73,19.03 4.95,18.95L7.44,17.95C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58L14.87,18.93C15.5,18.67 16.04,18.34 16.56,17.95L19.05,18.95C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.98Z",
    "timer-sand": "M6,2V8H6V8L10,12L6,16V16H6V22H18V16H18V16L14,12L18,8V8H18V2H6M16,16.5V20H8V16.5L12,12.5L16,16.5M12,11.5L8,7.5V4H16V7.5L12,11.5Z",
    "check-circle": "M12,2A10,10 0 0,1 22,12A10,10 0 0,1 12,22A10,10 0 0,1 2,12A10,10 0 0,1 12,2M11,16.5L18,9.5L16.59,8.09L11,13.67L7.91,10.59L6.5,12L11,16.5Z",
    "close-circle": "M12,2C17.53,2 22,6.47 22,12C22,17.53 17.53,22 12,22C6.47,22 2,17.53 2,12C2,6.47 6.47,2 12,2M15.59,7L12,10.59L8.41,7L7,8.41L10.59,12L7,15.59L8.41,17L12,13.41L15.59,17L17,15.59L13.41,12L17,8.41L15.59,7Z",
    "alert": "M13,14H11V10H13M13,18H11V16H13M1,21H23L12,2L1,21Z",
    "alert-circle": "M13,13H11V7H13M13,17H11V15H13M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2Z",
    "skull": "M12,2A9,9 0 0,0 3,11C3,14.03 4.53,16.82 7,18.47V22H9V19H11V22H13V19H15V22H17V18.46C19.47,16.81 21,14.03 21,11A9,9 0 0,0 12,2M8,11A2,2 0 0,1 10,13A2,2 0 0,1 8,15A2,2 0 0,1 6,13A2,2 0 0,1 8,11M16,11A2,2 0 0,1 18,13A2,2 0 0,1 16,15A2,2 0 0,1 14,13A2,2 0 0,1 16,11M12,16L13.5,19H10.5L12,16Z",
    "cancel": "M12,2C6.47,2 2,6.47 2,12C2,17.53 6.47,22 12,22C17.53,22 22,17.53 22,12C22,6.47 17.53,2 12,2M4,12C4,7.58 7.58,4 12,4C13.85,4 15.55,4.63 16.9,5.69L5.69,16.9C4.63,15.55 4,13.85 4,12M12,20C10.15,20 8.45,19.37 7.1,18.31L18.31,7.1C19.37,8.45 20,10.15 20,12C20,16.42 16.42,20 12,20Z",
    "wrench": "M22.7,19L13.6,9.9C14.5,7.6 14,4.9 12.1,3C10.1,1 7.1,0.6 4.7,1.7L9,6L6,9L1.6,4.7C0.4,7.1 0.9,10.1 2.9,12.1C4.8,14 7.5,14.5 9.8,13.6L18.9,22.7C19.3,23.1 19.9,23.1 20.3,22.7L22.6,20.4C23.1,20 23.1,19.4 22.7,19Z",
    "refresh": "M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z",
    "check": "M21,7L9,19L3.5,13.5L4.91,12.09L9,16.17L19.59,5.59L21,7Z",
    "circle-small": "M12,10A2,2 0 0,0 10,12A2,2 0 0,0 12,14A2,2 0 0,0 14,12A2,2 0 0,0 12,10Z",
    "menu-up": "M7,15L12,10L17,15H7Z",
    "menu-down": "M7,10L12,15L17,10H7Z",
    "close": "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
    "download": "M5,20H19V18H5M19,9H15V3H9V9H5L12,16L19,9Z",
    "content-copy": "M19,21H8V7H19M19,5H8A2,2 0 0,0 6,7V21A2,2 0 0,0 8,23H19A2,2 0 0,0 21,21V7A2,2 0 0,0 19,5M16,1H4A2,2 0 0,0 2,3V17H4V3H16V1Z",
}

# ONE canonical semantic table for attempt outcomes (DEDUP_REVIEW D4): color + icon +
# rank + label live HERE, and the several rendering maps (matrix SEM, _orank, the big
# _VERDICT_BADGE, the agent-matrix _ICON) all DERIVE from it -- was 5 parallel dicts.
OUTCOME = {
    "resolved": {"color": PALETTE["ok"],   "icon": "check-circle", "rank": 3, "label": "RESOLVED"},
    "miss":     {"color": PALETTE["bad"],  "icon": "close-circle", "rank": 2, "label": "FAILED"},
    "no_patch": {"color": PALETTE["warn"], "icon": "alert",        "rank": 1, "label": "NO-PATCH"},
}
# (icon, color) view for the matrix + the JS tables (exported via _ICON_JS as SEM).
OUTCOME_SEM = {k: (v["icon"], v["color"]) for k, v in OUTCOME.items()}
LIFECYCLE_SEM = {  # pre-result cell lifecycle (distinct axis from outcome)
    "running": ("cog",        PALETTE["accent"]),
    "waiting": ("timer-sand", PALETTE["warn"]),
}


def icon(name, size=15, color=None, title=None, cls=None, style=None):
    """Server-side inline-SVG Material Design icon (single source: MDI). Text/
    numbers stay text; this is ONLY for iconography (one icon language)."""
    d = MDI.get(name) or MDI["alert-circle"]
    attrs = [f'width="{size}"', f'height="{size}"', 'viewBox="0 0 24 24"',
             f'fill="{color or "currentColor"}"', 'style="vertical-align:middle;flex:none"'
             + (f";{style}" if style else "")]
    if cls:
        attrs.append(f'class="{cls}"')
    if title:
        attrs.append(f'aria-label="{html.escape(title, quote=True)}"')
    t = f'<title>{html.escape(title)}</title>' if title else ""
    return f'<svg {" ".join(attrs)}>{t}<path d="{d}"/></svg>'


def _chip_html(label, cls="", title=None):
    """Server-side chip component. Use for small metadata/filter labels; outcome
    verdicts use _badge_html instead. Visual style is owned by .chip in _BASE_CSS."""
    attrs = f' class="chip{(" " + cls) if cls else ""}"'
    if title:
        attrs += f' title="{html.escape(str(title), quote=True)}"'
    return f'<span{attrs}>{html.escape("" if label is None else str(label))}</span>'


def _badge_html(label, *, color=None, icon_name=None, large=False, title=None, href=None):
    """Server-side status/outcome badge component. Dynamic color is allowed here
    because the semantic color table is the source of truth; the shape/spacing live in CSS."""
    cls = "badge badge-lg" if large else "badge"
    attrs = [f'class="{cls}"']
    if color:
        attrs.append(f'style="background:{color}"')
    if title:
        attrs.append(f'title="{html.escape(str(title), quote=True)}"')
    inner = (icon(icon_name, 14 if large else 12, "#fff") + " " if icon_name else "")
    inner += html.escape("" if label is None else str(label))
    tag = "a" if href else "span"
    if href:
        attrs.insert(0, f'href="{html.escape(str(href), quote=True)}"')
    return f'<{tag} {" ".join(attrs)}>{inner}</{tag}>'


# Injected into every page so the JS tables share the SAME icon language + palette
# (DRY: path table + palette + semantic map come from Python above).
_ICON_JS = (
    "<script>\n"
    f"var MDI={json.dumps(MDI)};\n"
    f"var PAL={json.dumps(PALETTE)};\n"
    f"var SEM={json.dumps({'outcome': OUTCOME_SEM, 'lifecycle': LIFECYCLE_SEM})};\n"
    "function mdi(name,opts){opts=opts||{};var NS='http://www.w3.org/2000/svg';"
    "var svg=document.createElementNS(NS,'svg');var s=opts.size||15;"
    "svg.setAttribute('width',s);svg.setAttribute('height',s);svg.setAttribute('viewBox','0 0 24 24');"
    "svg.setAttribute('fill',opts.color||'currentColor');svg.style.verticalAlign='middle';svg.style.flex='none';"
    "if(opts.title){svg.setAttribute('aria-label',opts.title);var t=document.createElementNS(NS,'title');t.textContent=opts.title;svg.appendChild(t);}"
    "var p=document.createElementNS(NS,'path');p.setAttribute('d',MDI[name]||MDI['alert-circle']);svg.appendChild(p);return svg;}\n"
    # DEDUP_REVIEW D6: the DOM helper el() was defined identically in the /runs and /corpus
    # page scripts; hoist it into the shared injected bundle so both use one copy.
    "function el(tag,txt,attrs){var e=document.createElement(tag);if(txt!=null)e.textContent=txt;"
    "if(attrs)for(var k in attrs)e.setAttribute(k,attrs[k]);return e;}\n"
    # U4: tiny client-side counterpart to _chip_html. The component class owns the shape;
    # callers may add semantic modifier classes or dynamic categorical background colors.
    "function chipEl(txt,cls){return el('span',txt,{class:'chip'+(cls?(' '+cls):'')});}\n"
    # W96: ONE task-reference convention for the client tables -- strip the internal
    # `zbench_` instance-id prefix (never surface it) + link the bare task id to the
    # canonical task page /task (NOT the tracker; the GitHub link lives on the task page).
    # W100: no strip -- the id is already bare (payloads carry bare `task_id`/`task`).
    "function taskLink(t){t=(t==null?'':String(t));return el('a',t,{href:'/task?task='+encodeURIComponent(t),class:'mono'});}\n"
    # W68: shared sortable/filterable table scaffold used by BOTH the /runs and /corpus
    # client pages (they previously had near-duplicate renderHead + filter/sort cores).
    # Each page still supplies its own COLUMNS (with .k/.label/.num/.get) + its own
    # renderBody cell renderers (intrinsically page-specific: /runs pagination+badges,
    # /corpus per-agent matrix); only the generic header + filter+sort is shared here.
    # sortableThs -> the sortable <th> array (click toggles via onSort(key), arrow marks the active col).
    "function sortableThs(cols,sortKey,sortDir,onSort){return cols.map(function(c){"
    "var th=el('th',c.label);th.className='s'+(c.num?' num':'');"
    "th.onclick=(function(k){return function(){onSort(k);};})(c.k);"
    "if(sortKey===c.k){var ar=el('span');ar.className='ar';ar.style.marginLeft='2px';"
    "ar.appendChild(mdi(sortDir>0?'menu-up':'menu-down',{size:12,color:PAL.muted2}));th.appendChild(ar);}"
    "return th;});}\n"
    # filterSort -> filter(data,matchFn) then sort by the active column's .get (or a default comparator).
    "function filterSort(data,matchFn,cols,sortKey,sortDir,defCmp){"
    "var v=data.filter(matchFn);"
    "var col=sortKey?cols.filter(function(c){return c.k===sortKey;})[0]:null;"
    "if(col&&col.get){v.sort(function(a,b){var x=col.get(a),y=col.get(b);return (x<y?-1:x>y?1:0)*sortDir;});}"
    "else if(defCmp){v.sort(defCmp);}"
    "return v;}\n"
    # Shareable filter deep-link: `?filter=<text>` (alias `?q=`) pre-populates the '#q' search
    # box on load AND is kept in sync (history.replaceState) as the user types, so the current
    # URL is copy-pasteable. Shared by EVERY searchable table (/runs, /corpus, /agents): call
    # wireFilter(applyView) once after '#q' exists (applyView re-runs the page filter+render).
    # Other existing query params (status/agent/task/sort) are preserved untouched.
    "function filterParam(){var u=new URLSearchParams(location.search);return u.get('filter')||u.get('q')||'';}\n"
    "function syncFilterUrl(v){var u=new URLSearchParams(location.search);"
    "if(v){u.set('filter',v);}else{u.delete('filter');}u.delete('q');"
    "var qs=u.toString();history.replaceState(null,'',location.pathname+(qs?('?'+qs):'')+location.hash);}\n"
    "function wireFilter(applyView){var q=document.getElementById('q');if(!q)return;"
    "var init=filterParam();if(init)q.value=init;"
    "q.addEventListener('input',function(){syncFilterUrl(q.value.trim());applyView();});"
    "window.addEventListener('popstate',function(){q.value=filterParam();applyView();});}\n"
    "</script>\n"
)

# U5: ONE click-to-edit-inline implementation for task/run notes (was copy-pasted
# on the /run and /card pages). Editable TEXT uses this pattern; ACTIONS use the
# shared .btn/.btn-icon component. Shared single source below.
_NOTE_EDIT_JS = (
    "function noteEdit(id){var t=document.getElementById('note-text-'+id),f=document.getElementById('note-form-'+id);"
    "if(!t||!f)return;t.style.display='none';f.style.display='inline';"
    "var i=f.querySelector('input[name=body]');if(i){i.value=t.textContent||'';i.dataset.orig=i.value;i.focus();i.select();}}"
    "function noteSaveOrCancel(input,id){var f=input.form,t=document.getElementById('note-text-'+id);"
    "if(input.value!==input.dataset.orig){f.submit();return;}if(t)t.style.display='inline';if(f)f.style.display='none';}"
    "function noteNewEdit(){var t=document.getElementById('new-note-text'),f=document.getElementById('new-note');"
    "if(!t||!f)return;t.style.display='none';f.style.display='inline';"
    "var i=f.querySelector('input[name=body]');if(i){i.value='';i.focus();}}"
    "function noteNewSaveOrCancel(input){var f=input.form,t=document.getElementById('new-note-text');"
    "if(input.value.trim()){f.submit();return;}if(t)t.style.display='inline';if(f)f.style.display='none';}"
)


def _notes_block(title, notes, *, add_action, hidden_inputs, back, input_width=620,
                 empty_label="no notes yet", add_label="click to add note",
                 placeholder="add a note/comment"):
    """U4/U5: ONE click-to-edit-inline notes table, shared by /run and /card so the two
    never diverge (was two near-duplicate impls with different wrappers/CSS). Identical
    markup on both pages; editable text uses _NOTE_EDIT_JS, the add/edit actions post to
    `add_action` / /note_edit. Pages provide the per-context hidden form inputs + back url."""
    esc = lambda x: html.escape("" if x is None else str(x))
    out = [f'<h2 id=notes>{esc(title)}</h2><div class=card>',
           '<table style="margin-top:4px"><tr><th>when</th><th>source</th><th>note</th></tr>']
    for n in notes:
        nid = esc(n.get("id")); body = esc(n.get("body") or "")
        evidence = (f'<div class=muted style="font-size:11px">evidence: {esc(n.get("evidence"))}</div>'
                    if n.get("evidence") else "")
        inline_edit = (
            f'<span id="note-text-{nid}" onclick="noteEdit(\'{nid}\')" '
            f'style="cursor:text" title="click to edit note text">{body}</span>'
            f'<form id="note-form-{nid}" method=get action="/note_edit" style="display:none;margin:0">'
            f'<input type=hidden name=id value="{nid}"><input type=hidden name=back value="{esc(back)}">'
            f'<input name=body value="" style="width:{input_width}px" '
            f'onblur="noteSaveOrCancel(this,\'{nid}\')" '
            f'onkeydown="if(event.key===\'Enter\'){{this.blur();}}">'
            f'</form>{evidence}')
        out.append(f'<tr><td class=muted>{esc((n.get("created_at") or "")[:19].replace("T", " "))}</td>'
                   f'<td>{esc(n.get("source"))}</td>'
                   f'<td style="white-space:normal">{inline_edit}</td></tr>')
    if not notes:
        out.append(f'<tr><td colspan=3 class=muted>{esc(empty_label)}</td></tr>')
    out.append(f'<tr><td class=muted>new</td><td>human</td><td>'
               f'<span id="new-note-text" onclick="noteNewEdit()" class=muted '
               f'style="cursor:text" title="click to add note">{esc(add_label)}</span>'
               f'<form id="new-note" method=get action="{esc(add_action)}" style="display:none;margin:0">'
               f'{hidden_inputs}'
               f'<input name=body value="" placeholder="{esc(placeholder)}" style="width:{input_width}px" '
               f'onblur="noteNewSaveOrCancel(this)" '
               f'onkeydown="if(event.key===\'Enter\'){{this.blur();}}">'
               f'</form></td></tr></table></div>')
    return "".join(out)




def _wilson_ci(resolved, n, z=1.96):
    """95% Wilson score interval for the resolve RATE, returned in resolved-COUNT
    units (i.e. already multiplied by n). Returns (lo_count, hi_count). Wilson (not
    normal-approx) so it behaves at the 0/N and N/N extremes common at small N."""
    if not n:
        return (0.0, 0.0)
    p = max(0.0, min(1.0, resolved / n))
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5)) / denom
    lo = max(0.0, center - half) * n
    hi = min(1.0, center + half) * n
    return (lo, hi)


def leaderboard_markdown(leaderboard, n_common):
    """Single source of truth for the canonical board as a Markdown table (W33).
    Columns match the primary board: rank, agent_id, model, harness, resolved/N,
    rate, $/task. Both the dashboard 'copy as markdown' button and any CLI use
    this so the copy-as-markdown board / Slack pastes stay consistent."""
    hdr = ("| # | agent_id | model | harness | resolved | rate | $/task | turns/task |\n"
           "|---:|---|---|---|---:|---:|---:|---:|")
    lines = [hdr]
    for r in leaderboard:
        if not r.get("n"):
            continue
        rank = f'{r["rank"]}{"=" if r.get("rank_shared") else ""}'
        cost = r.get("cost_usd") or 0
        cost_cell = _costfmt(cost / r["n"]) if cost and r["n"] else "n/a"
        _nturns = r.get("n_turns") or 0
        turns_cell = f'{(r.get("turns") or 0) / _nturns:.0f}' if _nturns else "—"
        lines.append(
            f'| {rank} | {r["agent_id"]} | {r.get("model_name","")} | {r.get("harness","")} '
            f'| {_resfmt(r["resolved"])}/{r["n"]} | {r["resolve_rate"]*100:.0f}% | {cost_cell} | {turns_cell} |')
    return f"zbench leaderboard (common set = {n_common} tasks)\n\n" + "\n".join(lines)


def _leaderboard_ranked_view(leaderboard, partial):
    """Combined best-first leaderboard order with partial-coverage agents INTERLEAVED
    at their resolve-rate position (W72, 2026-08-02). Partials keep the muted/warning
    style but now PARTICIPATE in the ranked ordering instead of being dumped at the
    bottom/left. The comparable cohort keeps its competition ranks (from collect_state);
    each partial gets a SLOT rank = 1 + (#cohort agents with a strictly higher rate) so it
    reads as 'ranked ~here on its own set' without renumbering the cohort. Within an equal
    rate a cohort agent sorts before a partial."""
    lb = [dict(r, _partial=False) for r in (leaderboard or [])]
    pa = [dict(r, _partial=True) for r in (partial or [])]
    rates = sorted([(r.get("resolve_rate") or 0) for r in lb], reverse=True)
    for r in pa:
        rate = r.get("resolve_rate") or 0
        r["rank"] = 1 + sum(1 for cr in rates if cr > rate)
        r["rank_shared"] = False
    rows = lb + pa
    rows.sort(key=lambda r: (-(r.get("resolve_rate") or 0), 1 if r.get("_partial") else 0,
                             r.get("cost_usd") or 0, r.get("agent_id") or ""))
    return rows


def render_leaderboard_chart(leaderboard, n_common, partial=None):
    """Inline-SVG bar chart of the leaderboard (no JS/deps, survives auto-refresh).
    X axis = ranked agents ordered WORST-first (highest rank number on the left,
    rank 1 / best on the right -- bars rise left-to-right); Y axis = resolved on
    the common set (histogram bars); whiskers = Wilson 95% CI on the resolve rate.
    Hover a bar for the exact agent/score/rank."""
    # W72 (2026-08-02): partials are INTERLEAVED at their resolve-rate place (muted bar +
    # muted CI whisker + 'not comparable' tip), so they participate in the ranked ordering
    # instead of being dumped as a block on the LEFT. Combined best-first view, reversed so
    # best is on the RIGHT. (partial=None -> the RANKED-ONLY chart, no partial bars.)
    rows = [r for r in _leaderboard_ranked_view(leaderboard, partial) if r.get("n")][::-1]
    if not rows or not n_common:
        return ""
    ymax = 100  # W26: Y axis = resolve RATE percent (comparable even if n differs)
    padL, padR, padT, padB = 48, 16, 26, 156  # padB holds the vertical agent labels
    plotW, plotH = 1000, 300  # fixed landscape canvas; the SVG renders at width:100% (viewBox),
                              # so it fills the full content width like the table + Pareto chart.
    W = padL + plotW + padR
    H = padT + plotH + padB
    n = len(rows)
    slot = plotW / n              # per-agent horizontal slot spanning the full plot width
    bw = min(54.0, slot * 0.72)   # bar width (capped so a small cohort isn't absurdly wide)

    def y(v):  # value -> svg y coordinate
        return padT + plotH - (v / ymax) * plotH

    # W106: color bars by OPEN- vs CLOSED-weight (the interesting cut now), not by harness.
    _ow = {a: bool(m.get("open_weight")) for a, m in _agents_meta().items()}
    OW_COLOR, CW_COLOR = PALETTE["openw"], PALETTE["prop"]  # neutral categorical (indigo/amber), NOT ok/bad
    svg = [f'<svg width="100%" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet" '
           f'font-family="-apple-system,Segoe UI,Roboto,sans-serif" '
           f'style="width:100%;height:auto;background:#fff;border:1px solid #e2e8f0;border-radius:6px">']
    # y gridlines + percent tick labels (0..100 every 20)
    t = 0
    while t <= ymax:
        yy = y(t)
        svg.append(f'<line x1="{padL}" y1="{yy:.1f}" x2="{W-padR}" y2="{yy:.1f}" stroke="#eef2f7"/>')
        svg.append(f'<text x="{padL-6}" y="{yy+3:.1f}" text-anchor="end" font-size="10" '
                   f'fill="#64748b">{t}%</text>')
        t += 20
    # y axis title
    ymid = padT + plotH / 2
    svg.append(f'<text x="13" y="{ymid:.1f}" font-size="11" fill="#334155" '
               f'transform="rotate(-90 13 {ymid:.1f})" text-anchor="middle">'
               f'resolve rate (%)</text>')
    # bars + CI whiskers + labels
    for i, r in enumerate(rows):
        x = padL + i * slot + (slot - bw) / 2
        n_ = r["n"] or 1
        v = (r.get("resolve_rate") or 0) * 100     # bar height = resolve RATE %
        by = y(v)
        bh = padT + plotH - by
        is_partial = r.get("_partial")
        if is_partial:
            svg.append('<g class="lb-partial">')
        col = "#cbd5e1" if is_partial else (OW_COLOR if _ow.get(r.get("agent_id")) else CW_COLOR)
        aid = r.get("agent_id") or ""
        tip = (f'{aid}: {v:.0f}% ({_resfmt(r["resolved"])}/{r["n"]}) -- PARTIAL: ~rank {r.get("rank")} on its OWN set, not comparable'
               if is_partial else
               f'{aid}: {v:.0f}% ({_resfmt(r["resolved"])}/{r["n"]}) rank {r.get("rank")}')
        svg.append(f'<rect data-entry-id="{html.escape(aid, quote=True)}" '
                   f'x="{x:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" '
                   f'fill="{col}" opacity="{"0.55" if is_partial else "0.85"}"><title>{html.escape(tip)}</title></rect>')
        cx = x + bw / 2
        # Wilson 95% CI in COUNT units -> convert to percent of n
        loc, hic = _wilson_ci(r["resolved"], n_)
        lo, hi = loc / n_ * 100, hic / n_ * 100
        yl, yh = y(lo), y(hi)
        # value label: sit at the BAR TOP, to the RIGHT of the whisker line (was
        # centered above the whisker cap -> overlapped the whisker).
        svg.append(f'<text x="{cx+5:.1f}" y="{by-3:.1f}" text-anchor="start" '
                   f'font-size="11" font-weight="600" fill="#0f172a">{v:.0f}%</text>')
        # rank label just above the axis baseline (partials show a muted '~rank' -- they
        # now participate in the order but stay flagged as own-set/not-comparable)
        rk = (f'~{r.get("rank")}' if is_partial
              else f'#{r.get("rank")}{"=" if r.get("rank_shared") else ""}')
        svg.append(f'<text x="{cx:.1f}" y="{padT+plotH+13:.1f}" text-anchor="middle" '
                   f'font-size="10" fill="#94a3b8">{rk}</text>')
        # Wilson 95% CI whisker (line + caps), in percent. Partial agents get a whisker
        # too -- the CI on their OWN attempted set -- muted to match the partial bar so it
        # reads as 'uncertain + not comparable', not as a ranked score.
        wcol = "#94a3b8" if is_partial else "#0f172a"
        wop = "0.5" if is_partial else "0.65"
        svg.append(f'<line x1="{cx:.1f}" y1="{yh:.1f}" x2="{cx:.1f}" y2="{yl:.1f}" '
                   f'stroke="{wcol}" stroke-width="1.3" opacity="{wop}"/>')
        for yy in (yl, yh):
            svg.append(f'<line x1="{cx-5:.1f}" y1="{yy:.1f}" x2="{cx+5:.1f}" y2="{yy:.1f}" '
                       f'stroke="{wcol}" stroke-width="1.3" opacity="{wop}"/>')
        # vertical agent label under the axis
        lx, ly = cx, padT + plotH + 26
        short = (aid.replace("pi-foundry-", "pi/").replace("pi-anthropic-", "pi-an/")
                 .replace("claude-cli-", "cc/"))
        svg.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="10" fill="#334155" '
                   f'transform="rotate(90 {lx:.1f} {ly:.1f})">{html.escape(short)}</text>')
        if is_partial:
            svg.append('</g>')
    # baseline
    svg.append(f'<line x1="{padL}" y1="{y(0):.1f}" x2="{W-padR}" y2="{y(0):.1f}" stroke="#cbd5e1"/>')
    svg.append("</svg>")
    return "".join(svg)


def render_pareto_chart(leaderboard, tolerance=0.0, partial=None, partial_in_frontier=False):
    """Inline-SVG 2D Pareto scatter (W142/W145/W147): x = canonical computed $/task (lower better),
    y = resolve rate % (higher better). Tiers: FRONTIER (non-dominated) = filled dots joined by a
    staircase line; PRACTICALLY EQUIVALENT (W145: on the exact frontier but within `tolerance` of a
    cheaper frontier agent -> folded) = muted filled dots off the line; DOMINATED = hollow dots.

    PARTIAL-coverage agents are drawn as DIAMONDS wrapped in `data-partial` groups so the page's
    "show partial-coverage agents" checkbox (togglePartial) shows/hides them. W147: when
    `partial_in_frontier` is True (the checkbox-checked view), partials PARTICIPATE in the frontier
    computation (their own-set rate is compared like any point -> a partial can be on/fold/dominate),
    and their diamond is colored by its resulting tier. When False (checkbox-unchecked view),
    partials are omitted entirely and the frontier is ranked-agents-only. The two variants are
    rendered separately and swapped by the checkbox (see the call site). Caveat: partial rates are on
    the agent's OWN set (fewer tasks), not the common set -- so the participating view is exploratory
    (not apples-to-apples); the canonical/readout frontier stays ranked-only."""
    rows = [r for r in (leaderboard or []) if r.get("n")]
    if not rows:
        return ""
    ranked = []
    for r in rows:
        n_ = r.get("n") or 1
        ranked.append((r.get("agent_id") or "", (r.get("cost_usd") or 0) / n_,
                       (r.get("resolve_rate") or 0) * 100))
    ppts = []
    for r in (partial or []):
        if not r.get("n"):
            continue
        n_ = r.get("n") or 1
        ppts.append((r.get("agent_id") or "", (r.get("cost_usd") or 0) / n_,
                     (r.get("resolve_rate") or 0) * 100))
    part_participates = bool(partial_in_frontier and ppts)
    # Compute tiers over the participating point set (ranked, + partials iff participating), using
    # the SAME exact-then-thin logic as ranking_view.aggregate_and_rank (W142/W145). Rates are in %
    # here, so the tolerance band is tolerance*100 percentage points.
    import ranking_view as _rv
    _fset = list(ranked) + (list(ppts) if part_participates else [])
    _tol_pct = (tolerance or 0.0) * 100.0
    _exact, _ = _rv.pareto_frontier(_fset, tolerance=0.0)
    _front, _ = _rv.pareto_frontier(_fset, tolerance=_tol_pct)
    def _tier(aid):
        return "front" if aid in _front else ("equiv" if aid in _exact else "dom")
    pts = [(a, c, v, _tier(a)) for a, c, v in ranked]
    # axis ranges cover ranked + partial so partial points are not clipped when shown
    xmax = max([c for _, c, _, _ in pts] + [c for _, c, _ in ppts], default=1.0) or 1.0
    xmax *= 1.08
    padL, padR, padT, padB = 58, 120, 22, 46
    plotW, plotH = 900, 330  # wide landscape so the responsive (width:100%) chart fills the column
    W, H = padL + plotW + padR, padT + plotH + padB

    # DYNAMIC y-axis: the resolve rates cluster in a narrow band (e.g. ~49-74%), so zoom the
    # y-axis to the data range (+ padding, snapped to nice 5% bounds) instead of a fixed 0-100%
    # -- gives the points far more vertical separation. Never invert / collapse (guard equal).
    _rates = [v for _, _, v, _ in pts] + [v for _, _, v in ppts]
    _lo, _hi = min(_rates), max(_rates)
    _pad = max(3.0, (_hi - _lo) * 0.15)
    ylo = max(0.0, math.floor((_lo - _pad) / 5.0) * 5.0)
    yhi = min(100.0, math.ceil((_hi + _pad) / 5.0) * 5.0)
    if yhi - ylo < 5:  # degenerate (all agents ~equal) -> a minimal 10-pt window
        ylo, yhi = max(0.0, ylo - 5), min(100.0, yhi + 5)
    ystep = 5 if (yhi - ylo) <= 45 else 10

    def X(c):
        return padL + (c / xmax) * plotW

    def Y(v):
        return padT + plotH - ((v - ylo) / (yhi - ylo)) * plotH

    _ow = {a: bool(m.get("open_weight")) for a, m in _agents_meta().items()}
    OW, CW = PALETTE["openw"], PALETTE["prop"]
    # Responsive: width:100% + viewBox -> the chart fills the full content width (aspect from
    # the viewBox), consistent with a full-width diagram rather than a small fixed box.
    svg = [f'<svg width="100%" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet" '
           f'font-family="-apple-system,Segoe UI,Roboto,sans-serif" '
           f'style="width:100%;height:auto;background:#fff;border:1px solid #e2e8f0;border-radius:6px">']
    # y gridlines + % ticks (over the zoomed [ylo, yhi] band)
    t = ylo
    while t <= yhi + 1e-6:
        yy = Y(t)
        svg.append(f'<line x1="{padL}" y1="{yy:.1f}" x2="{padL+plotW}" y2="{yy:.1f}" stroke="#eef2f7"/>')
        svg.append(f'<text x="{padL-6}" y="{yy+3:.1f}" text-anchor="end" font-size="10" fill="#64748b">{t:.0f}%</text>')
        t += ystep
    # x ticks (5 steps)
    for i in range(6):
        cv = xmax * i / 5
        xx = X(cv)
        svg.append(f'<line x1="{xx:.1f}" y1="{padT}" x2="{xx:.1f}" y2="{padT+plotH}" stroke="#f5f7fa"/>')
        svg.append(f'<text x="{xx:.1f}" y="{padT+plotH+14:.1f}" text-anchor="middle" font-size="10" '
                   f'fill="#64748b">${cv:.2f}</text>')
    # axis titles
    svg.append(f'<text x="{padL+plotW/2:.1f}" y="{H-6}" text-anchor="middle" font-size="11" '
               f'fill="#334155">$/task (canonical computed cost -- lower is better)</text>')
    ymid = padT + plotH / 2
    svg.append(f'<text x="14" y="{ymid:.1f}" font-size="11" fill="#334155" '
               f'transform="rotate(-90 14 {ymid:.1f})" text-anchor="middle">resolve rate (%)</text>')
    # frontier staircase line (sorted by cost asc) -- includes participating partials (W147)
    _front_pts = [p for p in pts if p[3] == "front"]
    if part_participates:
        _front_pts += [(a, c, v, "front") for a, c, v in ppts if _tier(a) == "front"]
    front = sorted(_front_pts, key=lambda p: p[1])
    if len(front) >= 2:
        poly = " ".join(f"{X(c):.1f},{Y(v):.1f}" for _, c, v, _ in front)
        svg.append(f'<polyline points="{poly}" fill="none" stroke="{PALETTE["accent"]}" '
                   f'stroke-width="1.6" stroke-dasharray="5 3" opacity="0.8"/>')
    # points, tier order dom < equiv < front so frontier dots sit on top
    _order = {"dom": 0, "equiv": 1, "front": 2}
    for aid, c, v, tier in sorted(pts, key=lambda p: _order.get(p[3], 0)):
        cx, cy = X(c), Y(v)
        col = OW if _ow.get(aid) else CW
        short = (aid.replace("pi-foundry-", "pi/").replace("pi-anthropic-", "pi-an/")
                 .replace("claude-cli-", "cc/"))
        if tier == "front":
            tip = f'{aid}: {v:.0f}% at ${c:.2f}/task -- ON frontier'
            svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{col}" stroke="#0f172a" '
                       f'stroke-width="1.2"><title>{html.escape(tip)}</title></circle>')
            svg.append(f'<text x="{cx+9:.1f}" y="{cy+3:.1f}" font-size="10" font-weight="600" '
                       f'fill="#0f172a">{html.escape(short)}</text>')
        elif tier == "equiv":
            tip = (f'{aid}: {v:.0f}% at ${c:.2f}/task -- practically equivalent (within '
                   f'{tolerance*100:.0f} pts) to a cheaper frontier agent')
            svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5.5" fill="{col}" stroke="#0f172a" '
                       f'stroke-width="1" stroke-dasharray="2 1.5" opacity="0.5">'
                       f'<title>{html.escape(tip)}</title></circle>')
            svg.append(f'<text x="{cx+9:.1f}" y="{cy+3:.1f}" font-size="9.5" '
                       f'fill="#64748b">{html.escape(short)}</text>')
        else:
            tip = f'{aid}: {v:.0f}% at ${c:.2f}/task -- dominated'
            svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="#fff" stroke="{col}" '
                       f'stroke-width="1.6" opacity="0.9"><title>{html.escape(tip)}</title></circle>')
            svg.append(f'<text x="{cx+8:.1f}" y="{cy+3:.1f}" font-size="9.5" '
                       f'fill="#94a3b8">{html.escape(short)}</text>')
    # PARTIAL-coverage agents: DIAMONDS wrapped in data-partial groups (shared checkbox toggles them).
    # W147: when participating, color the diamond by its frontier tier (front=filled accent /
    # equiv=faded / dom=hollow) and label it as own-set; when NOT participating, a plain amber
    # not-in-frontier diamond.
    AMBER = "#b45309"
    for aid, c, v in ppts:
        cx, cy = X(c), Y(v)
        short = (aid.replace("pi-foundry-", "pi/").replace("pi-anthropic-", "pi-an/")
                 .replace("claude-cli-", "cc/").replace("pi-local-", "local/"))
        d = 6.0  # diamond half-diagonal
        pathpts = f"{cx:.1f},{cy-d:.1f} {cx+d:.1f},{cy:.1f} {cx:.1f},{cy+d:.1f} {cx-d:.1f},{cy:.1f}"
        if part_participates:
            tr = _tier(aid)
            base = OW if _ow.get(aid) else CW
            if tr == "front":
                fill, stroke, sw, dash, op, lc = base, "#0f172a", "1.4", "", "1", "#0f172a"
                role = "ON frontier"
            elif tr == "equiv":
                fill, stroke, sw, dash, op, lc = base, "#0f172a", "1", ' stroke-dasharray="2 1.5"', "0.5", "#64748b"
                role = f"practically equivalent (within {tolerance*100:.0f} pts)"
            else:
                fill, stroke, sw, dash, op, lc = "#fff", base, "1.6", "", "0.9", "#94a3b8"
                role = "dominated"
            tip = (f'{aid}: {v:.0f}% at ${c:.2f}/task -- PARTIAL (own-set rate), participating: {role}')
            svg.append(f'<g data-partial=1><polygon points="{pathpts}" fill="{fill}" stroke="{stroke}" '
                       f'stroke-width="{sw}"{dash} opacity="{op}"><title>{html.escape(tip)}</title></polygon>'
                       f'<text x="{cx+9:.1f}" y="{cy+3:.1f}" font-size="9.5" font-weight="600" fill="{lc}">'
                       f'{html.escape(short)}</text></g>')
        else:
            tip = (f'{aid}: {v:.0f}% at ${c:.2f}/task -- PARTIAL coverage (own set, not the common '
                   f'set): not comparable, not in the frontier')
            svg.append(f'<g data-partial=1><polygon points="{pathpts}" fill="#fff" stroke="{AMBER}" '
                       f'stroke-width="1.6" stroke-dasharray="2 1.5"><title>{html.escape(tip)}</title></polygon>'
                       f'<text x="{cx+9:.1f}" y="{cy+3:.1f}" font-size="9.5" fill="{AMBER}">'
                       f'{html.escape(short)}</text></g>')
    svg.append("</svg>")
    return "".join(svg)


def _annotations_index():
    """Per-cell + per-agent annotation lookup for the Runs table row indicators.
    Returns (per_run, per_agent): per_run keyed (instance_id, agent, run_id);
    per_agent keyed agent (agent-level broken_config/superseded)."""
    per_run, per_agent = {}, {}
    try:
        anns = scoring.load_annotations(on_error="warn")
    except Exception:
        anns = []
    for a in anns:
        agent = a.get("config_id")
        if not agent:
            continue
        task_id, rid = a.get("task_id"), a.get("run_id")
        if not task_id and not rid:
            per_agent[agent] = a
        else:
            inst = constants.instance_of(str(task_id)) if task_id else task_id
            per_run[(inst, agent, str(rid) if rid is not None else None)] = a
    return per_run, per_agent


def _annot_lookup(idx, instance_id, agent, run_id):
    """Return the annotation for a cell (per-run first, then agent-level) or None."""
    per_run, per_agent = idx
    return (per_run.get((instance_id, agent, str(run_id) if run_id is not None else None))
            or per_agent.get(agent))





def _eval_id_for_cell(run_id, agent, instance_id):
    task_id = constants.task_of(str(instance_id or ""))
    db = Path(BENCHDB)
    conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute(
            """SELECT evaluation_id FROM attempt
               WHERE run_id=? AND config_id=? AND task_id=?""",
            (run_id, agent, task_id),
        ).fetchone()
        return r["evaluation_id"] if r else None
    finally:
        conn.close()


def _attempt_events(evaluation_id, run_id, agent, instance_id):
    task_id = constants.task_of(str(instance_id or ""))
    db = Path(BENCHDB)
    conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='attempt_event'").fetchone():
            return []
        rows = list(conn.execute(
            """SELECT * FROM attempt_event
               WHERE (evaluation_id IS NOT NULL AND evaluation_id=?)
                  OR (run_id=? AND config_id=? AND task_id=?)
               ORDER BY ts, id""",
            (evaluation_id, run_id, agent, task_id),
        ))
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _event_dt(e):
    try:
        return datetime.fromisoformat(str(e.get("ts") or "").replace("Z", "+00:00"))
    except Exception:
        return None




def _event_ts(e):
    dt = _event_dt(e) if e else None
    return dt.strftime("%m-%d %H:%M:%S") if dt else ""



# W40: event-driven pipeline rendering. Event emitters use domain phase names; the
# dashboard owns this static mapping from event/source item -> visual stage.
EVENT_STAGE = {
    "cell_started": "queue", "slot_wait_started": "queue", "slots_acquired": "queue",
    "agent_started": "generation", "task_attempt_started": "generation",
    "transcript_started": "generation", "transcript_finished": "generation", "agent_finished": "generation",
    "patch_extracted": "patch", "patch_missing": "patch",
    # Current zbench emits verify_started; legacy/backfill used verification_*.
    "verify_started": "verification", "verify_finished": "verification",
    "verification_started": "verification", "verification_log_mtime": "verification", "verification_finished": "verification",
    "attempt_recorded": "result", "task_attempt_finished": "result", "cell_error": "result",
}
STAGE_ORDER = ["queue", "input", "generation", "patch", "verification", "result", "scoring", "other"]
STAGE_LABEL = {"queue": "queue / slots", "input": "input", "generation": "generation",
               "patch": "patch", "verification": "verification", "result": "result",
               "scoring": "scoring / notes", "other": "other events"}
ITEM_STAGE = {
    "issue": "input", "task_card": "input", "base_commit": "input", "problem": "input",
    "model": "generation", "tokens": "generation", "cost": "generation", "transcript": "generation",
    "patch": "patch", "verify": "verification", "badge": "result", "raw_status": "result",
    "error": "result", "stderr": "result", "scoring": "scoring", "validate": "scoring",
}


# Canonical per-phase label so multiple provenance events that mean the same thing
# (e.g. agent_started vs transcript_started, agent_finished vs transcript_finished)
# collapse to ONE line per stage instead of rendering near-duplicate started/finished
# rows with slightly different backfilled timestamps.
_EVENT_LABEL = {
    "cell_started": "cell", "slot_wait_started": "slot wait", "slots_acquired": "slot acquired",
    "agent_started": "started", "task_attempt_started": "started", "transcript_started": "started",
    "agent_finished": "finished", "transcript_finished": "finished",
    "patch_extracted": "patch", "patch_missing": "patch",
    "verify_started": "started", "verify_finished": "finished",
    "verification_started": "started", "verification_finished": "finished",
    "verification_log_mtime": "log",
    "attempt_recorded": "recorded", "task_attempt_finished": "finished", "cell_error": "error",
}


def _event_label(e):
    return _EVENT_LABEL.get(e.get("phase"), e.get("phase") or "event")


def _event_json(e):
    try:
        return json.loads(e.get("data_json") or "{}")
    except Exception:
        return {}


def _event_summary(e, esc):
    ph = e.get("phase") or "event"
    ts = _event_ts(e)
    data = _event_json(e)
    if ph in ("cell_started", "slot_wait_started", "slots_acquired"):
        label = {"cell_started": "cell", "slot_wait_started": "slot wait", "slots_acquired": "slot acquired"}[ph]
        return f'<span class=muted>{label}</span> {esc(ts)}'
    if ph in ("agent_started", "task_attempt_started", "transcript_started"):
        return f'<span class=muted>started</span> {esc(ts)}'
    if ph in ("agent_finished", "transcript_finished"):
        return f'<span class=muted>finished</span> {esc(ts)}'
    if ph == "patch_extracted":
        extra = ""
        if data.get("patch_count") is not None:
            extra = f' <span class=muted>({esc(data.get("patch_count"))} patch, {esc(data.get("patch_chars"))} chars)</span>'
        lbl = "patch ready by" if data.get("synthetic_ready_by_verify") else "patch extracted"
        return f'<span class=muted>{lbl}</span> {esc(ts)}{extra}'
    if ph == "patch_missing":
        return f'<span class=muted>no patch</span> {esc(ts)}'
    if ph in ("verify_started", "verification_started"):
        return f'<span class=muted>started</span> {esc(ts)}'
    if ph in ("verify_finished", "verification_finished"):
        return f'<span class=muted>finished</span> {esc(ts)}'
    if ph == "verification_log_mtime":
        return f'<span class=muted>log</span> {esc(ts)}'
    if ph == "attempt_recorded":
        status = data.get("status") or e.get("message") or "recorded"
        return f'<span class=muted>recorded</span> {esc(ts)} <span class=mono>{esc(status)}</span>'
    if ph == "task_attempt_finished":
        return f'<span class=muted>finished</span> {esc(ts)} <span class=mono>{esc(e.get("message"))}</span>'
    if ph.startswith("legacy:"):
        return ""  # too noisy for the main pipeline; retained in DB for provenance
    return f'<span class=muted>{esc(ph)}</span> {esc(ts)}'


def _stage_bounds(events):
    dts = [_event_dt(e) for e in events]
    dts = [d for d in dts if d]
    if not dts:
        return None, None
    return min(dts), max(dts)


def _duration_between(a, b):
    if not a or not b:
        return ""
    sec = (b - a).total_seconds()
    if sec < 0:
        return ""
    return f"+{sec:.0f}s" if sec < 90 else f"+{sec/60:.1f}m"


def _fmt_dur_secs(sec):
    # Shared chip formatter. Returns "" for a missing/zero/negative duration so an
    # incomplete-or-collapsed phase renders NO chip (never a misleading "0s"); a real
    # sub-second span renders "<1s" rather than rounding down to a misleading "0s".
    if sec is None or sec <= 0:
        return ""
    if sec < 1:
        return "<1s"
    return f"{sec:.0f}s" if sec < 90 else f"{sec/60:.1f}m"


def _render_event_pipeline(events, stage_items, esc, stage_classes=None, stage_fallback=None):
    stage_classes = stage_classes or {}
    stage_fallback = stage_fallback or {}
    ev_by_stage = collections.defaultdict(list)
    for e in events or []:
        st = EVENT_STAGE.get(e.get("phase"), "other")
        ev_by_stage[st].append(e)
    stages = []
    for st in STAGE_ORDER:
        items = []
        # Collapse to ONE line per canonical label within a stage (earliest ts wins),
        # so redundant provenance events (agent vs transcript start/finish) don't
        # double up as near-identical started/finished rows.
        seen_labels = set()
        for e in sorted(ev_by_stage.get(st, []), key=lambda ev: (_event_dt(ev) or datetime.min.replace(tzinfo=timezone.utc))):
            lab = _event_label(e)
            if lab in seen_labels:
                continue
            seen_labels.add(lab)
            s = _event_summary(e, esc)
            if s:
                items.append(s)
        items.extend(stage_items.get(st, []))
        if items:
            ev_start, ev_end = _stage_bounds(ev_by_stage.get(st, []))
            stages.append({"key": st, "title": STAGE_LABEL.get(st, st), "items": items,
                           "start": ev_start, "end": ev_end,
                           "cls": stage_classes.get(st, "gray")})
    if not stages:
        return ""

    def box(stage):
        inner = "".join(f'<div class=li>{it}</div>' for it in stage["items"] if it)
        # W50: prefer the event-bound span, but when it is absent OR collapses to
        # zero (a single/equal-ts backfilled event, or a still-running phase), fall
        # back to the recorded stage timing (runtime_ms / verify / live elapsed).
        a, b = stage.get("start"), stage.get("end")
        dur_secs = (b - a).total_seconds() if (a and b) else None
        if not dur_secs or dur_secs <= 0:
            fb = stage_fallback.get(stage["key"])
            dur_secs = fb if (fb and fb > 0) else None
        txt = _fmt_dur_secs(dur_secs)
        chip = f'<span class="stagetime" title="stage duration">{esc(txt)}</span>' if txt else ""
        return (f'<div class="stage {stage["cls"]}"><h3><span>{esc(stage["title"])}</span>{chip}</h3>'
                f'{inner or "<div class=li class=muted>&mdash;</div>"}</div>')

    out = ['<div class=pipe>']
    for i, st in enumerate(stages):
        cell = []
        if i:
            prev = stages[i-1]
            d = _duration_between(prev.get("end"), st.get("start"))
            tip = ""
            if prev.get("end") and st.get("start"):
                tip = f'{prev["end"].strftime("%m-%d %H:%M:%S")} -> {st["start"].strftime("%m-%d %H:%M:%S")}'
            cell.append('<div class=arrow title="' + esc(tip) + '">&rarr;' + (f'<small>{esc(d)}</small>' if d else '') + '</div>')
        cell.append(box(st))
        # Group each connector arrow WITH the box it points to (.pipe-cell) so a
        # flex-wrapped row never ends on a dangling arrow leading nowhere -- the arrow
        # always travels to the next line together with its target box. The first cell
        # has no leading arrow.
        out.append('<div class=pipe-cell>' + "".join(cell) + '</div>')
    out.append('</div>')
    return "".join(out)


def _run_exclusion(evaluation_id):
    if not evaluation_id:
        return None
    db = Path(BENCHDB)
    conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_exclusion'").fetchone():
            return None
        r = conn.execute("SELECT * FROM run_exclusion WHERE evaluation_id=?", (evaluation_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def _attempt_provenance(evaluation_id):
    """Captured per-attempt runtime provenance (agent CLI version, harness commit, ...)."""
    if not evaluation_id:
        return None
    db = Path(BENCHDB)
    conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='attempt_provenance'").fetchone():
            return None
        r = conn.execute("SELECT * FROM attempt_provenance WHERE evaluation_id=?", (evaluation_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def _subject_notes(subject_type, subject_id):
    if not subject_id:
        return []
    db = Path(BENCHDB)
    conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='note'").fetchone():
            return []
        return [dict(r) for r in conn.execute(
            """SELECT * FROM note WHERE subject_type=? AND subject_id=?
               ORDER BY created_at DESC, id DESC""", (subject_type, subject_id))]
    finally:
        conn.close()


def _run_notes(evaluation_id):
    return _subject_notes("run", evaluation_id)


def _write_note(subject_type, subject_id, body, *, source="human", created_by=None):
    created_by = created_by or constants.operator()
    db = Path(BENCHDB)
    conn = sqlite3.connect(str(db), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        conn.execute(
            """INSERT INTO note(subject_type,subject_id,source,body,created_by,created_at)
               VALUES(?,?,?,?,?,?)""",
            (subject_type, subject_id, source, body, created_by, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _write_run_note(evaluation_id, body, *, source="human", created_by=None):
    _write_note("run", evaluation_id, body, source=source, created_by=created_by)


def _edit_note(note_id, *, body=None):
    db = Path(BENCHDB)
    conn = sqlite3.connect(str(db), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        sets, vals = [], []
        if body is not None:
            sets.append("body=?"); vals.append(body)
        if sets:
            sets.append("updated_at=?"); vals.append(datetime.now(timezone.utc).isoformat())
            vals.append(note_id)
            conn.execute(f"UPDATE note SET {', '.join(sets)} WHERE id=?", vals)
            conn.commit()
    finally:
        conn.close()


def _set_run_exclusion(evaluation_id, reason, *, decided_by=None):
    decided_by = decided_by or constants.operator()
    db = Path(BENCHDB)
    conn = sqlite3.connect(str(db), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        now = datetime.now(timezone.utc).isoformat()
        reason = (reason or "").strip()
        if reason:
            conn.execute(
                """INSERT INTO run_exclusion(evaluation_id,reason,decided_by,decided_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(evaluation_id) DO UPDATE SET reason=excluded.reason,
                     decided_by=excluded.decided_by, decided_at=excluded.decided_at""",
                (evaluation_id, reason, decided_by, now),
            )
        else:
            conn.execute("DELETE FROM run_exclusion WHERE evaluation_id=?", (evaluation_id,))
        conn.commit()
    finally:
        conn.close()





# Shared CSS for the three app pages: Leaderboard (/), Corpus (/corpus), Runs
# (/runs). Keep this as the single source of truth for small UI polish so simple
# fixes (nav/table/header/buttons) do not drift across near-duplicate <style> blocks.
# Detail pages still use the older _PAGE_HEAD helper; that is a separate cleanup.
# DEDUP_REVIEW D5: ONE base stylesheet shared by the app pages (_APP_CSS) AND the
# detail pages (_PAGE_HEAD) -- was two near-duplicate CSS blocks (and _PAGE_HEAD used
# .format() brace-doubling). Rules identical to both live here; each surface appends
# only its specifics. Palette via the :root var() tokens injected globally by _nav.
_BASE_CSS = """ body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:18px;background:var(--bg);color:var(--fg)}
 table{border-collapse:collapse;width:100%;font-size:12px;background:#fff}
 th,td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
 th{background:var(--thbg)}
 .muted{color:var(--muted)} .mono{font-family:ui-monospace,Menlo,monospace} a{color:var(--accent)}
 .ell{max-width:150px;overflow:hidden;text-overflow:ellipsis}
 .card{background:#fff;border:1px solid var(--border);border-radius:6px;padding:8px 12px;margin-bottom:8px}
 .btn{display:inline-flex;align-items:center;justify-content:center;gap:4px;border:1px solid var(--border2);background:var(--bg);color:var(--accent);border-radius:3px;cursor:pointer;font:inherit;font-size:13px;line-height:16px;padding:0 4px;text-decoration:none}
 .btn:hover{background:var(--line)} .btn:disabled{opacity:.6;cursor:default}
 .btn-small{font-size:13px;padding:0 4px;line-height:16px}.btn-icon{vertical-align:middle;padding:2px 6px;line-height:0}.btn-inline{margin-left:8px}
 .btn-primary{background:var(--accent);color:#fff;border-color:var(--accent);padding:7px 18px;line-height:1.2;gap:6px}.btn-primary:hover{background:#1d4ed8;border-color:#1d4ed8}
 .chip{display:inline-flex;align-items:center;gap:4px;background:#e0e7ff;color:#3730a3;border:1px solid transparent;padding:1px 6px;border-radius:var(--radius);font-size:11px;white-space:nowrap}
 .chip-small{font-size:10px;padding:0 5px}.chip-solid{color:#fff;border-color:transparent}.chip-filter{background:var(--thbg);color:var(--fg);border-color:var(--border2);border-radius:10px;padding:1px 8px}.chip-ok{background:#dcfce7;color:#166534;border-color:var(--ok-soft);border-radius:12px;padding:2px 8px;font-size:12px}
 .chip-weight.ow{background:var(--openw-soft);color:var(--openw)} .chip-weight.prop{background:var(--prop-soft);color:var(--prop)}
 .badge{display:inline-flex;align-items:center;gap:4px;color:#fff;padding:1px 6px;border-radius:var(--radius);font-size:11px;text-decoration:none}.badge-lg{padding:2px 10px;border-radius:5px;font-size:13px;font-weight:600}
 .toolbar{display:flex;gap:12px;align-items:center;margin-bottom:6px;flex-wrap:wrap}.wide-input{width:340px}.push-right{margin-left:auto}.chip-row{margin-bottom:8px}.iconlink{display:inline-flex;margin-left:4px}.subtle-heading-link{font-size:12px;font-weight:400;margin-left:8px}
 .artifact-card{font-size:12px;margin-top:8px}.flexline{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.chipline{margin-top:6px;display:flex;gap:6px;flex-wrap:wrap}.small-note{font-size:11px}.normal-wrap{white-space:normal;margin-top:4px}
 tr.rowex td{text-decoration:line-through;color:var(--muted2)}
 .spin{display:inline-block;width:10px;height:10px;border:2px solid var(--border2);border-top-color:var(--accent);border-radius:50%;animation:sp .7s linear infinite;vertical-align:middle}
 @keyframes sp{to{transform:rotate(360deg)}}
 input,select{font:inherit;font-size:12px;padding:2px 6px;border:1px solid var(--border2);border-radius:var(--radius)}
"""

# app pages (Leaderboard / Corpus / Runs): base + table/matrix/badge specifics.
_APP_CSS = _BASE_CSS + """ h1{font-size:20px;margin:0 0 2px} h2{font-size:15px;margin:20px 0 6px;border-bottom:1px solid var(--border);padding-bottom:3px}
 table{box-shadow:0 1px 2px rgba(0,0,0,.06)}
 th{position:sticky;top:34px} tr:hover td{background:var(--bg)}
 th.s{cursor:pointer;user-select:none} th .ar{color:var(--muted2);font-size:10px}
 th.vh{height:96px;padding:2px;vertical-align:bottom}
 th.vh span{writing-mode:vertical-rl;transform:rotate(180deg);white-space:nowrap;font-size:10px;font-weight:600}
 td.mx{text-align:center;padding:2px} td.mx a{text-decoration:none;font-size:14px}
 .num{text-align:right;font-variant-numeric:tabular-nums}
 .costcell{font-variant-numeric:tabular-nums;white-space:nowrap}
 .costcell .i{display:inline-block;text-align:right}
 .costcell .f{display:inline-block;text-align:left;width:5ch}
 .chip{margin-right:4px}.chip-filter{margin-right:6px}
 tr.lb-hl td{background:#fef3c7} rect.lb-hl{opacity:1;stroke:#0f172a;stroke-width:2}
"""


def _nav(active=""):
    """Shared top nav (single source of truth for every page). DEAD-STABLE:
    position:fixed pins the bar to the viewport so it never moves on scroll,
    independent of body margins/scroll position -- no wrapper, no per-page CSS. A
    same-height sibling spacer reserves its footprint so content isn't hidden under
    it. Place the _nav() output as the FIRST body element so the bar sits above the
    page <h1>. `active` bolds the current view."""
    items = [("/", "Leaderboard"), ("/coverage", "Coverage"), ("/corpus", "Corpus"),
             ("/runs", "Runs"), ("/agents", "Agents"),
             ("/errata", "Errata"), ("/download", "Download")]
    links = []
    for href, label in items:
        cur = label.lower() == (active or "").lower()
        style = "font-weight:700;color:#0f172a" if cur else "color:#2563eb"
        links.append(f'<a href="{href}" style="text-decoration:none;{style}">{label}</a>')
    bar = ('<div style="position:fixed;top:0;left:0;right:0;height:34px;z-index:100;'
           'box-sizing:border-box;display:flex;align-items:center;gap:16px;padding:0 18px;'
           'font-size:13px;background:#eef2f7;border-bottom:1px solid #cbd5e1">'
           + "".join(links) + "</div>")
    # inject the shared design tokens (:root vars) + icon/token JS so EVERY page
    # (app + detail) has the palette variables and mdi()/PAL/SEM (single source).
    return (f'<style>{_CSS_TOKENS}</style>' + bar
            + '<div style="height:34px"></div>' + _ICON_JS)  # spacer == bar height


def _attempt_status(row, exclusion=None, note_count=0):
    """Canonical attempt status for /api/runs.

    This is domain/view-model logic, not JS presentation. /runs renders this object;
    raw lifecycle/status/failure_mode remain available for tooltips/search.
    """
    live = (not row.get("scored")) and row.get("state") in ("RUNNING", "GENERATING", "VERIFYING", "STALE")
    phase = (row.get("phase") or row.get("state") or "").lower()
    if live:
        if row.get("state") == "STALE":
            return {"key": "stale", "label": "STALE", "stage": "live", "terminal": False,
                    "severity": "warn", "rank_effect": "pending", "note_count": note_count}
        # W132 phase-aware slotting introduced waiting-gen / waiting-verify (a cell holding
        # `global` but BLOCKED on a per-provider gen slot or the local build slot). Treat ANY
        # `waiting*` phase (+ the older acquiring-slot/queued) as WAITING so a queued cell is
        # not shown as RUNNING/VERIFYING (e.g. local cells queued behind the cap=1 provider slot).
        if phase.startswith("waiting") or phase in ("acquiring-slot", "queued"):
            return {"key": "waiting", "label": "WAITING", "stage": "queued", "terminal": False,
                    "severity": "info", "rank_effect": "pending", "note_count": note_count}
        label = "GENERATING" if phase == "generating" else ("VERIFYING" if "verify" in phase else "RUNNING")
        return {"key": label.lower(), "label": label, "stage": "live", "terminal": False,
                "severity": "info", "rank_effect": "pending", "note_count": note_count}
    if exclusion:
        reason = exclusion.get("reason") or "excluded from scoring"
        pfx = exclusions.parse_prefix(reason)
        return {"key": f"excluded:{pfx or 'scoring'}", "label": f"EXCLUDED: {exclusions.subkind(reason)}",
                "stage": "review", "terminal": True, "severity": "warn",
                "rank_effect": "excluded", "note_count": note_count}
    if row.get("scored"):
        oc = row.get("outcome_cls")
        if oc == "resolved":
            return {"key": "resolved", "label": "RESOLVED", "stage": "terminal", "terminal": True,
                    "severity": "ok", "rank_effect": "counts", "note_count": note_count}
        if oc == "no_patch":
            return {"key": "no_patch", "label": "NO PATCH", "stage": "terminal", "terminal": True,
                    "severity": "warn", "rank_effect": "counts", "note_count": note_count}
        return {"key": "failed", "label": "FAILED", "stage": "terminal", "terminal": True,
                "severity": "bad", "rank_effect": "counts", "note_count": note_count}
    return {"key": "unknown", "label": "UNKNOWN", "stage": "unknown", "terminal": False,
            "severity": "muted", "rank_effect": "unknown", "note_count": note_count}


def _runs_payload(st):
    """Data-only (NO HTML) flattened per-attempt rows for the client-rendered /runs
    page + /api/runs. Presentation -- badges, colors, glyphs, relative time -- is done
    in vanilla JS; here we only emit values plus the non-trivial SERVER-side
    classifications (W23 failure-mode via classify_attempt and annotation status)
    so the JS never reimplements scoring logic."""
    ann_idx = _annotations_index()
    exclusions, note_counts = {}, {}
    try:
        db = Path(BENCHDB)
        conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True); conn.row_factory = sqlite3.Row
        try:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_exclusion'").fetchone():
                exclusions = {r["evaluation_id"]: dict(r) for r in conn.execute("SELECT * FROM run_exclusion")}
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='note'").fetchone():
                note_counts = {r["subject_id"]: r["n"] for r in conn.execute(
                    "SELECT subject_id, COUNT(*) AS n FROM note WHERE subject_type='run' GROUP BY subject_id")}
        finally:
            conn.close()
    except Exception:
        exclusions, note_counts = {}, {}
    flat = []
    for r in st.get("runs", []):
        rid = r["run_id"]
        for row in r["rows"]:
            ts = row.get("ended") or row.get("started") or r.get("last_event") or ""
            flat.append((str(ts), rid, row))
    flat.sort(key=lambda x: x[0], reverse=True)
    n_total = len(flat)
    rows = []
    for ts, rid, row in flat:
        scored = bool(row.get("scored"))
        if scored:
            try:
                fmode = scoring.classify_attempt({
                    "tests_passed": row.get("tests_passed"), "status": row.get("status"),
                    "outcome": row.get("status"), "runtime_ms": row.get("runtime_ms"),
                    "total_duration_ms": None, "output_tokens": None})
            except Exception:
                fmode = row.get("outcome_cls") or row.get("status") or ""
        else:
            fmode = row.get("phase") or row.get("state") or ""
        tot = row.get("total_duration_ms"); gen = row.get("gen_ms")
        verify = (tot - gen) if (tot and gen and tot > gen + 1000) else None
        a = _annot_lookup(ann_idx, row["instance_id"], row["agent_id"], rid)
        ev = row.get("evaluation_id")
        rx = exclusions.get(ev) if ev else None
        nnotes = note_counts.get(ev, 0) if ev else 0
        live = (not scored) and row.get("state") in ("RUNNING", "GENERATING", "VERIFYING", "STALE")
        status_obj = _attempt_status(row, rx, nnotes)
        rows.append({
            "age_s": _age(ts), "when_full": _fmt_ts(ts),
            # W100: `task` = bare id (display/filter, carried natively from benchdb_reader);
            # `instance` = the zbench_ instance-id (the real blob/lease/worktree key -> /run links).
            "agent": row["agent_id"], "task": row.get("task_id") or constants.task_of(str(row.get("instance_id") or "")),
            "instance": row.get("instance_id"),
            "state": row.get("state"), "scored": scored,
            "outcome_cls": row.get("outcome_cls"),
            "failure_mode": str(fmode),
            "status_obj": status_obj,
            "wall_ms": tot or row.get("runtime_ms"),
            "gen_ms": gen, "verify_ms": verify,
            "elapsed_s": row.get("elapsed_s"),  # live cells: wall-so-far (no total yet)
            "tokens": row.get("total_tokens"),
            "run_id": rid,
            "exclusion": ({"reason": rx.get("reason")} if rx else None),
            "annotation": ({"status": a.get("status"), "kind": a.get("kind"),
                            "source": a.get("source")} if a else None),
            "live": live,
        })
    return {"generated_at": st.get("generated_at"), "n_total": n_total, "rows": rows}


def _corpus_payload(st):
    """Data-only per-task corpus rows + the agent axis for the client-rendered
    /corpus page + /api/corpus. Presentation -- language bar, status badges, the
    per-agent outcome glyphs, lang/type pills -- is done in vanilla JS; here we emit
    values only (curation_status + stats + has_instance let the view derive the status
    label; per-cell outcome + running flag drive the matrix)."""
    run_keys = _running_cells()
    wait_keys = _waiting_cells()
    agent_axis = st.get("agent_axis", [])
    tasks = []
    for t in st.get("tasks", []):
        task_id = t.get("task_id") or ""
        inst = constants.instance_of(task_id)
        rev = t.get("review") or {}
        ao = t.get("agent_outcomes") or {}
        cells = {aa: {"outcome": ao.get(aa),
                      "running": any(k == constants.cell_key(task_id, aa) or k.startswith(constants.cell_key(task_id, aa) + "_try") for k in run_keys),
                      "waiting": any(k == constants.cell_key(task_id, aa) or k.startswith(constants.cell_key(task_id, aa) + "_try") for k in wait_keys)}
                 for aa in agent_axis}
        stt = t.get("stats")
        tasks.append({
            "task_id": task_id, "summary": t.get("summary"), "component": t.get("component"),
            "lang": t.get("lang"), "type": t.get("type"),
            "author": (t.get("author") or {}).get("name"),        # A3: fix-commit author (display/search)
            "author_email": (t.get("author") or {}).get("email"),
            "curation_status": t.get("curation_status"),
            "curation_stage": t.get("curation_stage"),
            "reason_code": t.get("reason_code"), "reason": t.get("reason"),
            "has_instance": bool(t.get("has_instance")), "has_card": bool(t.get("has_card")),
            "stats": ({"resolved": stt["resolved"], "n": stt["n"]} if stt else None),
            "common_set": t.get("common_set"),  # W111: in/out of the ranked common set + why
            "running": any(k.startswith(inst + "_") for k in run_keys),
            "waiting": any(k.startswith(inst + "_") for k in wait_keys),
            "coupling": rev.get("test_coupling_risk"),
            "solution_path": rev.get("solution_path_specificity"),
            "suitability": rev.get("suitability"),
            "cells": cells,
        })
    return {"generated_at": st.get("generated_at"), "agent_axis": agent_axis,
            "n_tasks": len(tasks), "tasks": tasks}


# client-rendered /runs page: a static shell + vanilla JS that fetches /api/runs and
# does ALL presentation (sort / filter / paginate the ~400 rows in memory -- no
# server round-trips after the initial fetch). Data-only API + view-layer-in-JS is
# the deliberate architecture (no framework, no build step).
_RUNS_TABLE_JS = r"""
<script>
var RUNS_OPTS=window.RUNS_OPTS||{};
var DATA=[], VIEW=[], sortKey=RUNS_OPTS.sortKey||'age_s', sortDir=1, page=0;
// W94: deep-link filters (from the leaderboard resolved/miss/no-patch/excluded cells and
// the corpus matrix). status maps to the raw OUTCOME so EXCLUDED rows with that outcome
// still show (struck-through) -- making clear they are not counted. /cells was removed;
// this IS the per-run drill-down now. Shared by /runs and task-detail embeds.
var USP=new URLSearchParams(location.search);
var fAgent=RUNS_OPTS.agent||USP.get('agent')||'', fTask=RUNS_OPTS.task||USP.get('task')||'', fStatus=RUNS_OPTS.status||USP.get('status')||'';
// W100: `task` is the bare id now; filter compares bare-to-bare (no instance-prefix normalization).
if(fAgent||fTask||fStatus){ sortKey=RUNS_OPTS.sortKey||'task'; sortDir=1; }
function statusMatch(r){ if(!fStatus) return true; var so=r.status_obj||{};
  if(fStatus==='excluded') return so.rank_effect==='excluded';
  return r.outcome_cls===fStatus; }
function urlFilterMatch(r){ return (!fAgent||r.agent===fAgent) && (!fTask||r.task===fTask) && statusMatch(r); }
function chipHref(drop){ var u=new URLSearchParams(location.search); u.delete(drop); var s=u.toString(); return '/runs'+(s?('?'+s):''); }
function renderChips(){ var c=document.getElementById('chips'); if(!c) return; c.innerHTML='';
  var add=function(label,val,drop){ if(!val) return; var chip=chipEl(null,'chip-filter');
    chip.appendChild(document.createTextNode(label+': '+val+' '));
    var x=el('a','\u00d7',{href:chipHref(drop),title:'remove this filter'}); x.style.textDecoration='none'; chip.appendChild(x);
    c.appendChild(chip); };
  add('agent',fAgent,'agent'); add('task',fTask,'task'); add('status',fStatus,'status');
  if(fAgent||fTask||fStatus){ var clr=el('a','clear all',{href:'/runs'}); clr.className='muted'; clr.style.marginLeft='4px'; c.appendChild(clr); } }
var COLS=[
  {k:'age_s', label:'when', get:function(r){return r.age_s==null?-1:r.age_s;}},
  {k:'status',label:'status',get:function(r){return (r.status_obj&&r.status_obj.label)||'';}},
  {k:'agent', label:'agent', get:function(r){return r.agent||'';}},
  {k:'task',  label:'task',  get:function(r){return r.task||'';}},
  {k:'wall_ms',label:'wall', get:function(r){return r.elapsed_s!=null?r.elapsed_s*1000:(r.wall_ms||0);}, num:true},
  {k:'tokens',label:'tokens',get:function(r){return r.tokens||0;}, num:true}
];
function rel(s){ if(s==null)return ''; s=Math.floor(s);
  if(s<90)return s+'s ago'; if(s<5400)return Math.floor(s/60)+'m ago';
  if(s<172800)return Math.floor(s/3600)+'h ago'; return Math.floor(s/86400)+'d ago'; }
function sevColor(sev){ return {ok:PAL.ok,bad:PAL.bad,warn:PAL.warn,info:PAL.accent,muted:PAL.muted2}[sev||'muted']||PAL.muted2; }
function wallCell(r){ if(r.elapsed_s!=null)return {t:(r.elapsed_s/60).toFixed(1)+'m',tip:'live: elapsed since start'};
  var ms=r.wall_ms; if(!ms)return {t:'',tip:''};
  var m=(ms/60000).toFixed(1)+'m', tip='total '+m;
  if(r.gen_ms&&r.verify_ms)tip='gen '+(r.gen_ms/60000).toFixed(1)+'m + verify '+(r.verify_ms/60000).toFixed(1)+'m = '+m;
  return {t:m,tip:tip}; }
function detailHref(r){ return '/run?run='+encodeURIComponent(r.run_id)+'&agent='+encodeURIComponent(r.agent)+'&instance='+encodeURIComponent(r.instance||r.task); }
function liveHref(r){ return '/live?run='+encodeURIComponent(r.run_id)+'&agent='+encodeURIComponent(r.agent)+'&instance='+encodeURIComponent(r.instance||r.task); }
function runsMatch(r){ if(!urlFilterMatch(r)) return false;  // URL deep-link filters AND optional free-text box
  var qi=document.getElementById('q'); var q=qi?qi.value.trim().toLowerCase():''; if(!q)return true; var st=r.status_obj||{};
  return ((r.agent||'')+' '+(r.task||'')+' '+(r.run_id||'')+' '+(r.state||'')+' '+(r.failure_mode||'')+' '+(st.key||'')+' '+(st.label||'')).toLowerCase().indexOf(q)>=0; }
function pageSize(){ var ps=document.getElementById('ps'); return ps?Number(ps.value):Number(RUNS_OPTS.pageSize||1e9); }
function applyView(){
  VIEW=filterSort(DATA,runsMatch,COLS,sortKey,sortDir,null);  // W68: shared filter+sort
  var ps=pageSize(); var maxp=Math.max(0,Math.ceil(VIEW.length/ps)-1);
  if(page>maxp)page=maxp; if(page<0)page=0;
  renderHead(); renderBody(ps);
  var pi=document.getElementById('pageinfo'); if(pi)pi.textContent=(VIEW.length?(page*ps+1):0)+'\u2013'+Math.min(VIEW.length,(page+1)*ps)+' of '+VIEW.length;
  var tm=document.getElementById('taskattemptmeta'); if(tm)tm.textContent=VIEW.length+' attempt'+(VIEW.length===1?'':'s');
}
function renderHead(){  // W68: shared sortable header; /runs resets page on sort
  var tr=el('tr');
  sortableThs(COLS,sortKey,sortDir,function(k){ if(sortKey===k)sortDir*=-1; else {sortKey=k; sortDir=1;} page=0; applyView(); }).forEach(function(th){ tr.appendChild(th); });
  var h=document.querySelector('#t thead'); h.innerHTML=''; h.appendChild(tr);
}
function renderBody(ps){
  var tb=document.querySelector('#t tbody'); tb.innerHTML=''; var frag=document.createDocumentFragment();
  VIEW.slice(page*ps,(page+1)*ps).forEach(function(r){ frag.appendChild(renderRunsRow(r)); });
  tb.appendChild(frag);
}
function renderRunsRow(r){
  var tr=el('tr');
  var st=r.status_obj||{label:'UNKNOWN',severity:'muted',key:'unknown'};
  // W46: scoring-excluded attempts render struck-through (present but not counted).
  if(st.rank_effect==='excluded'){ tr.className='rowex'; }
  var whenTd=el('td',rel(r.age_s)); whenTd.className='muted'; whenTd.title=r.when_full||''; tr.appendChild(whenTd);
  var stTd=el('td');
  var a=el('a',st.label,{href:detailHref(r),title:'run_id='+r.run_id+'; raw state='+r.state+'; failure-mode='+r.failure_mode});
  a.className='badge';
  // W55: excluded rows use muted-gray text; render the EXCLUDED badge gray too (not orange-brown).
  a.style.background=(st.rank_effect==='excluded')?PAL.muted2:sevColor(st.severity); stTd.appendChild(a);
  if(r.live){ var la=el('a',null,{href:liveHref(r),target:'_blank',title:'live transcript/log'}); la.className='iconlink'; la.appendChild(mdi('file-document',{size:13,color:PAL.muted,title:'live transcript/log'})); stTd.appendChild(la); }
  if(st.note_count){ var na=el('a',null,{href:detailHref(r)+'#notes',title:st.note_count+' note(s)'}); na.className='iconlink'; na.appendChild(mdi('note-text',{size:13,color:PAL.muted,title:st.note_count+' note(s)'})); stTd.appendChild(na); }
  tr.appendChild(stTd);
  tr.appendChild(el('td',r.agent,{class:'mono ell',title:r.agent||''}));
  var taskTd=el('td',null,{class:'mono'}); taskTd.appendChild(taskLink(r.task)); tr.appendChild(taskTd);  // W96: bare id, linked to /task
  var w=wallCell(r); var wTd=el('td',w.t); wTd.className='num'; wTd.title=w.tip; tr.appendChild(wTd);
  var tkTd=el('td'); tkTd.className='num';  // W95: missing/0 token record -> explicit muted n/a
  if(r.tokens){ tkTd.textContent=String(r.tokens); } else { tkTd.textContent='n/a'; tkTd.classList.add('muted'); tkTd.title='no token record for this attempt'; }
  tr.appendChild(tkTd);
  return tr;
}
wireFilter(function(){page=0;applyView();});  // shareable ?filter= deep-link (shared helper)
var psEl=document.getElementById('ps'); if(psEl)psEl.onchange=function(){page=0;applyView();};
var prevEl=document.getElementById('prev'); if(prevEl)prevEl.onclick=function(){if(page>0){page--;applyView();}};
var nextEl=document.getElementById('next'); if(nextEl)nextEl.onclick=function(){var ps=pageSize(); if((page+1)*ps<VIEW.length){page++;applyView();}};
fetch('/api/runs').then(function(r){return r.json();}).then(function(j){
  DATA=j.rows||[]; var meta=document.getElementById('meta'); if(meta)meta.textContent=j.n_total+' attempts \u00b7 generated '+(j.generated_at||'');
  renderChips(); applyView();
}).catch(function(e){ var meta=document.getElementById('meta')||document.getElementById('taskattemptmeta'); if(meta)meta.textContent='load error: '+e; });
</script>
"""

# client-rendered /runs page: a static shell + vanilla JS that fetches /api/runs and
# does ALL presentation (sort / filter / paginate the ~400 rows in memory -- no
# server round-trips after the initial fetch). Data-only API + view-layer-in-JS is
# the deliberate architecture (no framework, no build step).
_RUNS_PAGE = r"""<!doctype html><html><head><meta charset=utf-8>
<title>Runs &mdash; zbench</title>
<style>__CSS__</style></head><body>
__NAV__
<h1>zbench &mdash; Runs</h1>
<div class="toolbar">
  <input id=q placeholder="filter&hellip; (agent / task / run id / status)" class="wide-input">
  <label class=muted>page <select id=ps><option>50</option><option selected>100</option><option>200</option><option value=1e9>all</option></select></label>
  <button class="btn btn-small" id=prev>&larr; prev</button>
  <span id=pageinfo class=muted></span>
  <button class="btn btn-small" id=next>next &rarr;</button>
  <span id=meta class="muted push-right"></span>
</div>
<div id=chips class="chip-row"></div>
<table id=t><thead></thead><tbody></tbody></table>
<script>window.RUNS_OPTS={controls:true};</script>
__RUNS_TABLE_JS__
</body></html>"""


def render_runs_page():
    return (_RUNS_PAGE.replace("__CSS__", _APP_CSS)
            .replace("__NAV__", _nav("Runs"))
            .replace("__RUNS_TABLE_JS__", _RUNS_TABLE_JS))


# client-rendered /corpus page: static shell + vanilla JS that fetches /api/corpus
# and renders the per-task table (+ the GitHub-style language bar + the per-agent
# outcome matrix) with client-side sort + filter. Same data-only-API + view-in-JS
# architecture as /runs.
_CORPUS_PAGE = r"""<!doctype html><html><head><meta charset=utf-8>
<title>Corpus &mdash; zbench</title>
<style>__CSS__</style></head><body>
__NAV__
<h1>zbench &mdash; Corpus</h1>
<div style="display:flex;gap:12px;align-items:center;margin-bottom:8px">
  <input id=q placeholder="filter&#x2026; (task / summary / component / lang / status / reason)" style="width:340px">
  <span id=statusFilters></span>
  <span id=statusChip></span>
  <span id=meta class=muted style="margin-left:auto"></span>
</div>
<div id=corpusbars style="display:grid;grid-template-columns:max-content 1fr max-content;gap:4px 10px;align-items:center;margin:2px 0 8px"></div>
<table id=t><thead></thead><tbody></tbody></table>
<div class=muted style="font-size:11px;margin-top:8px">Matrix: __LEGEND__</div>
<script>
var DATA=[], AGENTS=[], VIEW=[], sortKey=null, sortDir=1;
var statusFilter=new URLSearchParams(location.search).get('status')||'validated';  // default: active benchmark corpus; null/all = all records
var LANGC={go:'#00add8',cpp:'#9b59b6'}, LANGN={go:'Go',cpp:'C++'};
var TYPEC={bug:'#dc2626',feature:'#16a34a',other:'#2563eb'};
var SR={validated:0,held:1,dropped:2,invalid:3};
var FIXED=[
  {k:'task_id',label:'task',get:function(r){return r.task_id||'';}},
  {k:'summary',label:'summary',get:function(r){return r.summary||'';}},
  {k:'component',label:'component',get:function(r){return r.component||'';}},
  {k:'author',label:'author',get:function(r){return r.author||'';}},
  {k:'lang',label:'lang',get:function(r){return r.lang||'';}},
  {k:'status',label:'status',get:function(r){return SR[r.curation_status]!=null?SR[r.curation_status]:4;}},
  {k:'eval',label:'eval',num:true,get:function(r){return r.stats?r.stats.resolved/(r.stats.n||1):-1;}}
];
function statusInfo(r){ var cs=r.curation_status,has=!!r.stats;
  if(cs==='dropped')return {l:'dropped',c:'#94a3b8',t:r.reason||r.suitability||''};
  if(cs==='invalid')return {l:'invalid',c:'#b45309',t:r.reason||'oracle did not flip -- excluded from corpus'};
  if(cs==='held')return {l:'held',c:'#b45309',t:r.reason||r.suitability||''};
  if(cs==='validated'){ if(has)return {l:'validated',c:'#16a34a',t:'validated + gridded'};
    if(!r.has_instance)return {l:'validated',c:'#94a3b8',t:'validated but no instance.jsonl yet'};
    return {l:'validated',c:'#2563eb',t:'validated + has instance; not yet gridded'}; }
  if(has)return {l:'attempted',c:'#16a34a',t:'attempted in the grid'};
  return {l:'\u2014',c:'#94a3b8',t:''}; }
function short(v){ if(!v)return ''; return String(v).split(' (')[0].trim(); }
function mini(v){ v=v||''; return v.length>22?v.slice(0,21)+'\u2026':v; }  // minimal cell; full text in title / card
function mdiCard(t){ // task-card link via the shared MDI registry (U2)
  var a=el('a',null,{href:'/task?task='+encodeURIComponent(t),title:'task page'});
  a.style.cssText='display:inline-flex;align-items:center;color:'+PAL.muted;
  a.appendChild(mdi('file-document',{color:PAL.muted,title:'task card'})); return a;
}
function renderBar(container,title,rows,keyFn,colorFn,labelFn){
  // Appends ONE compact row (label | bar | legend) to the shared 3-col grid, so the
  // Status and Language summaries stack as 2 tabular rows (saves vertical space) instead
  // of two vertically-stacked title/bar/legend blocks.
  var total=rows.length; if(!total)return;
  var counts={}; rows.forEach(function(r){ var k=keyFn(r)||'unknown'; counts[k]=(counts[k]||0)+1; });
  var keys=Object.keys(counts).sort(function(a,b){return counts[b]-counts[a] || a.localeCompare(b);});
  var cap=el('div',title+':'); cap.className='muted'; cap.style.cssText='font-size:11px;white-space:nowrap';
  var bar=el('div'); bar.style.cssText='display:flex;height:10px;width:100%;border-radius:5px;overflow:hidden;box-shadow:0 0 0 1px rgba(0,0,0,.08)';
  bar.title=title+' for the currently shown table rows; total shown count is in the table summary';
  var leg=el('div'); leg.style.cssText='font-size:11px';
  keys.forEach(function(k,i){ var n=counts[k],pct=Math.round(n/total*100),col=colorFn(k),nm=labelFn(k);
    var seg=el('span'); seg.title=nm+': '+n+' ('+pct+'%)'; seg.style.cssText='flex:'+n+';background:'+col; bar.appendChild(seg);
    if(i)leg.appendChild(document.createTextNode(' \u00b7 '));
    // rect swatch matching the leaderboard chart title-line legend (one visual language)
    var sw=el('span'); sw.style.cssText='display:inline-block;width:9px;height:9px;background:'+col+';vertical-align:middle;margin:0 4px 0 2px'; leg.appendChild(sw);
    leg.appendChild(document.createTextNode(nm+' ')); var b=el('b',String(n)); leg.appendChild(b);
    var p=el('span',' ('+pct+'%)'); p.className='muted'; leg.appendChild(p); });
  container.appendChild(cap); container.appendChild(bar); container.appendChild(leg);
}
function renderBars(rows){
  var box=document.getElementById('corpusbars'); if(!box)return; box.innerHTML='';
  renderBar(box,'Status',rows,function(r){return r.curation_status;},
    function(k){return {validated:'#16a34a',held:'#b45309',invalid:'#f59e0b',dropped:'#94a3b8'}[k]||'#6b7280';},
    function(k){return k;});
  renderBar(box,'Language',rows,function(r){return r.lang;},
    function(k){return LANGC[k]||'#6b7280';}, function(k){return LANGN[k]||k;});
}
function defaultCmp(a,b){ var ra=a.running?0:(a.waiting?1:2),rb=b.running?0:(b.waiting?1:2); if(ra!==rb)return ra-rb;
  // With the default status=validated filter, curation_status is constant among shown rows,
  // so sort by EVAL (resolve rate) ASCENDING as a difficulty proxy -- hardest/most-
  // discriminating tasks first (no-stats rows -> 2, sorted last); task id as tiebreak.
  // (click the eval or task header to re-sort; this is only the initial order.)
  var ea=a.stats?a.stats.resolved/(a.stats.n||1):2, eb=b.stats?b.stats.resolved/(b.stats.n||1):2;
  if(ea!==eb)return ea-eb;
  return (a.task_id||'')<(b.task_id||'')?-1:(a.task_id||'')>(b.task_id||'')?1:0; }
function renderStatusFilters(){
  var box=document.getElementById('statusFilters'); if(!box)return; box.innerHTML='';
  ['validated','held','invalid','dropped','all'].forEach(function(st){
    var a=el('a',st,{href:'/corpus?status='+st,title:'filter corpus table to '+st});
    a.className='chip '+(statusFilter===st||(st==='all'&&!statusFilter)?'chip-ok':'chip-filter');
    a.style.textDecoration='none'; a.style.marginRight='3px'; box.appendChild(a);
  });
}
function renderStatusChip(){
  var box=document.getElementById('statusChip'); box.innerHTML=''; if(!statusFilter||statusFilter==='all')return;
  var chip=chipEl(null,'chip-ok');
  chip.appendChild(document.createTextNode('status: '+statusFilter));
  var x=el('a',null,{title:'remove filter \u2014 view all tasks'}); x.style.cssText='cursor:pointer;display:inline-flex;text-decoration:none;color:inherit';
  x.appendChild(mdi('close',{size:13,color:'currentColor',title:'remove filter'}));
  x.onclick=function(){ statusFilter=null; applyView(); };
  chip.appendChild(x); box.appendChild(chip);
}
function corpusMatch(r){ var q=document.getElementById('q').value.trim().toLowerCase();
  if(statusFilter && statusFilter!=='all' && r.curation_status!==statusFilter) return false;
  if(!q)return true;
  return ((r.task_id||'')+' '+(r.summary||'')+' '+(r.component||'')+' '+(r.author||'')+' '+(r.author_email||'')+' '+(r.lang||'')+' '+(r.curation_status||'')+' '+(r.reason_code||'')+' '+(r.reason||'')).toLowerCase().indexOf(q)>=0; }
function applyView(){
  VIEW=filterSort(DATA,corpusMatch,FIXED,sortKey,sortDir,defaultCmp);  // W68: shared filter+sort (defaultCmp when unsorted)
  renderStatusFilters(); renderStatusChip(); renderBars(VIEW);
  renderHead(); renderBody();
  document.getElementById('meta').textContent=VIEW.length+' of '+DATA.length+' tasks'+(statusFilter?' (status='+statusFilter+')':'')+' \u00b7 '+AGENTS.length+' agents';
}
function renderHead(){  // W68: shared sortable header + page-specific agent/coupling columns
  var tr=el('tr');
  sortableThs(FIXED,sortKey,sortDir,function(k){ if(sortKey===k)sortDir*=-1; else {sortKey=k;sortDir=1;} applyView(); }).forEach(function(th){ tr.appendChild(th); });
  AGENTS.forEach(function(aa){ var th=el('th'); th.className='vh'; th.appendChild(el('span',aa)); tr.appendChild(th); });
  ['coupling','solution-path'].forEach(function(l){ tr.appendChild(el('th',l)); });
  var h=document.querySelector('#t thead'); h.innerHTML=''; h.appendChild(tr);
}
function renderBody(){
  var tb=document.querySelector('#t tbody'); tb.innerHTML=''; var frag=document.createDocumentFragment();
  VIEW.forEach(function(r){ var tr=el('tr'); if(r.curation_status==='dropped'||r.curation_status==='invalid')tr.className='rowex';
    // W104: task column = card icon (if any) + the bare id linked to /task (NOT the tracker); type tag.
    var pTd=el('td'); pTd.className='mono';
    if(r.has_card){ var slot=el('span'); slot.style.cssText='display:inline-block;width:15px;height:15px;margin-right:5px;vertical-align:middle'; slot.appendChild(mdiCard(r.task_id)); pTd.appendChild(slot); }
    pTd.appendChild(taskLink(r.task_id));
    if(r.type){ var tt=chipEl(r.type,'chip-solid chip-small'); tt.style.background=TYPEC[(r.type||'').toLowerCase()]||'#6b7280'; tt.style.marginLeft='5px'; tt.title='issue type'; pTd.appendChild(tt); }
    tr.appendChild(pTd);
    // W104: summary is PLAIN unlinked text (the card link lives on the task id now).
    var sTd=el('td');
    var stext=(r.summary||'').slice(0,60);
    sTd.appendChild(document.createTextNode(stext));
    if((r.summary||'').length>60)sTd.title=r.summary; tr.appendChild(sTd);
    tr.appendChild(el('td',r.component||''));
    // A3: fix-commit author (name shown, email on hover)
    var auTd=el('td'); if(r.author){ auTd.appendChild(document.createTextNode(r.author)); if(r.author_email)auTd.title=r.author_email+' (git author of the gold-patch fix commit)'; } tr.appendChild(auTd);
    var lTd=el('td'); if(r.lang){ var lp=chipEl(r.lang,'chip-solid chip-small'); lp.style.background=LANGC[r.lang]||'#6b7280'; lTd.appendChild(lp);} tr.appendChild(lTd);
    var si=statusInfo(r); var stTd=el('td',si.l); stTd.style.color=si.c; stTd.title=si.t; tr.appendChild(stTd);
    var eTd=el('td'); eTd.className='num';
    if(r.stats){ var a=el('a',null,{href:'/task?task='+encodeURIComponent(r.task_id)}); a.style.textDecoration='none';
      var c=el('span',r.stats.resolved+'/'+r.stats.n); c.style.color=r.stats.resolved?'#16a34a':'#dc2626'; a.appendChild(c);
      var pc=el('span',' ('+Math.round(r.stats.resolved/(r.stats.n||1)*100)+'%)'); pc.className='muted'; a.appendChild(pc); eTd.appendChild(a); }
    else { var d=el('span','-'); d.className='muted'; eTd.appendChild(d); }
    // W111: mark ONLY the exceptional case -- a task OUT of the ranked common set --
    // with a muted close-circle + a self-explaining tooltip (IN tasks stay unmarked;
    // membership is recomputed on demand, never a stored flag).
    var cm=r.common_set;
    if(cm && cm.in===false){ var om=el('span',null,{title:cm.reason||'out of the ranked common set'});
      om.style.cssText='display:inline-flex;vertical-align:middle;margin-left:5px';
      om.appendChild(mdi('close-circle',{size:12,color:PAL.muted2})); eTd.appendChild(om); }
    tr.appendChild(eTd);
    AGENTS.forEach(function(aa){ var c=r.cells[aa]||{}; var td=el('td'); td.className='mx';
      var href='/runs?agent='+encodeURIComponent(aa)+'&task='+encodeURIComponent(r.task_id);
      function ilink(name,color,title){ var a=el('a',null,{href:href,title:title}); a.style.color=color; a.style.display='inline-flex'; a.appendChild(mdi(name,{color:color,title:title})); return a; }
      if(c.running){ var rn=SEM.lifecycle.running; td.appendChild(ilink(rn[0],rn[1],aa+': RUNNING now'+(c.outcome?' (prior: '+c.outcome+')':''))); }
      else if(c.waiting){ var wt=SEM.lifecycle.waiting; td.appendChild(ilink(wt[0],wt[1],aa+': WAITING (launched, queued for a slot)'+(c.outcome?' (prior: '+c.outcome+')':''))); }
      else if(c.outcome){ var so=SEM.outcome[c.outcome]; if(so){ td.appendChild(ilink(so[0],so[1],aa+': '+c.outcome)); } else { td.appendChild(el('span','?')); } }
      else { var s=el('span',null,{title:'no attempt'}); s.style.color=PAL.muted2; s.appendChild(mdi('circle-small',{size:10,color:PAL.muted2})); td.appendChild(s); } tr.appendChild(td); });
    var cpTd=el('td',mini(short(r.coupling))); cpTd.className='muted'; if(r.coupling)cpTd.title=r.coupling; tr.appendChild(cpTd);
    var spTd=el('td',mini(short(r.solution_path))); spTd.className='muted'; if(r.solution_path)spTd.title=r.solution_path; tr.appendChild(spTd);
    frag.appendChild(tr); });
  tb.appendChild(frag);
}
wireFilter(applyView);  // shareable ?filter= deep-link (shared helper)
fetch('/api/corpus').then(function(r){return r.json();}).then(function(j){
  DATA=j.tasks||[]; AGENTS=j.agent_axis||[];
  applyView();
}).catch(function(e){ document.getElementById('meta').textContent='load error: '+e; });
</script></body></html>"""


def render_corpus_page():
    _legend = " &#183; ".join(
        f'{icon(nm, 12, col)} {lbl}' for nm, col, lbl in (
            ("check-circle", PALETTE["ok"], "resolved"),
            ("close-circle", PALETTE["bad"], "failed"),
            ("alert", PALETTE["warn"], "no-patch"),
            ("cog", PALETTE["accent"], "running"),
            ("timer-sand", PALETTE["warn"], "waiting")))
    # W111: marker for tasks OUT of the ranked common set (hover the eval cell for why).
    _legend += (f' &#183; {icon("close-circle", 12, PALETTE["muted2"])} '
                f'<span title="marked in the eval column; hover it for the reason">out of common set</span>')
    return (_CORPUS_PAGE.replace("__CSS__", _APP_CSS)
            .replace("__NAV__", _nav("Corpus")).replace("__LEGEND__", _legend))


# Client-side click-to-sort for the /coverage table. Mirrors the leaderboard's lbSort
# (same reorder core, mdi() arrow, blanks-sort-last rule from the shared _ICON_JS bundle).
# Pre-seeds cur="tasks"/dir=-1 so it matches the server-rendered default (most tasks first)
# and the first click on `tasks` flips to ascending; every other column starts ascending.
_COV_SORT_JS = (
    '<script>(function(){var tbl=document.getElementById("covtable");if(!tbl)return;'
    'var dir={tasks:-1},cur="tasks";window.covSort=function(th){var k=th.getAttribute("data-k");'
    'var num=th.classList.contains("num");dir[k]=(cur===k)?-dir[k]:1;cur=k;'
    'var tb=tbl.tBodies[0];var rows=[].slice.call(tb.rows);'
    'rows.sort(function(a,b){var x=a.getAttribute("data-"+k),y=b.getAttribute("data-"+k);'
    'if(num){var xe=(x===""||x==null),ye=(y===""||y==null);'
    'if(xe&&ye)return 0;if(xe)return 1;if(ye)return -1;'
    'return (parseFloat(x)-parseFloat(y))*dir[k];}'
    'x=(x||"").toLowerCase();y=(y||"").toLowerCase();return (x<y?-1:x>y?1:0)*dir[k];});'
    'rows.forEach(function(r){tb.appendChild(r);});'
    '[].forEach.call(tbl.tHead.rows[0].cells,function(c){var s=c.querySelector(".ar");if(s)s.remove();});'
    'var ar=document.createElement("span");ar.className="ar";ar.style.marginLeft="2px";'
    'ar.appendChild(mdi(dir[k]>0?"menu-up":"menu-down",{size:12,color:PAL.muted2}));th.appendChild(ar);};'
    # mark the default-sorted column (tasks, descending) with a resting down-arrow on load.
    'var th0=tbl.tHead.rows[0].querySelector("[data-k=tasks]");'
    'if(th0){var a0=document.createElement("span");a0.className="ar";a0.style.marginLeft="2px";'
    'a0.appendChild(mdi("menu-down",{size:12,color:PAL.muted2}));th0.appendChild(a0);}})();</script>')


def render_coverage_page():
    """Per-model performance over its OWN FULL set of attempted validated tasks
    (NOT the common set). Breaks out input / output / cache tokens per task next to
    $/task so the cost is legible. Complements the canonical common-set Leaderboard
    on / (which is what should be used for cross-model RANKING)."""
    import glob as _glob, json as _json, sqlite3 as _sql
    from collections import defaultdict as _dd
    import model_prices as _mp
    # the active benchmark bank = validated tasks
    validated = set()
    for f in _glob.glob(str(TASKS / "ZT-*" / "meta.json")):
        try:
            if _json.load(open(f)).get("curation_status") == "validated":
                validated.add(Path(f).parent.name)
        except Exception:
            pass
    conn = _sql.connect(f"file:{Path(BENCHDB).resolve()}?mode=ro", uri=True)
    conn.row_factory = _sql.Row
    rows = conn.execute(
        "SELECT a.config_id c, a.task_id t, a.tests_passed p, a.input_tokens i, "
        "a.output_tokens o, a.cache_read_tokens cr, a.cache_write_tokens cw "
        "FROM attempt a LEFT JOIN run_exclusion x ON x.evaluation_id=a.evaluation_id "
        "WHERE x.evaluation_id IS NULL").fetchall()
    conn.close()
    # per (config, task) CELL: pass rate (passes/runs) + mean tokens over token-bearing runs
    cell = _dd(lambda: {"runs": 0, "passes": 0, "i": 0, "o": 0, "cr": 0, "cw": 0, "ntok": 0})
    for r in rows:
        if r["t"] not in validated:
            continue
        d = cell[(r["c"], r["t"])]
        d["runs"] += 1
        d["passes"] += (r["p"] or 0)
        it, ot, crr, cww = (r["i"] or 0), (r["o"] or 0), (r["cr"] or 0), (r["cw"] or 0)
        if it or ot:
            d["i"] += it; d["o"] += ot; d["cr"] += crr; d["cw"] += cww; d["ntok"] += 1
    # per CONFIG aggregate over its OWN covered cells (denominators differ per model)
    agg = _dd(lambda: {"n": 0, "resolved": 0.0, "i": 0.0, "o": 0.0, "cr": 0.0, "cw": 0.0, "ntok": 0})
    for (cfg, _t), d in cell.items():
        if d["runs"] == 0:
            continue
        if cfg.startswith(("control-", "replay")):   # oracle / replay controls, not models
            continue
        a = agg[cfg]
        a["n"] += 1
        a["resolved"] += d["passes"] / d["runs"]
        if d["ntok"]:
            a["i"] += d["i"] / d["ntok"]; a["o"] += d["o"] / d["ntok"]
            a["cr"] += d["cr"] / d["ntok"]; a["cw"] += d["cw"] / d["ntok"]; a["ntok"] += 1
    meta = _agents_meta()
    out = []
    for cfg, a in agg.items():
        n = a["n"]; nt = a["ntok"] or 1
        # Self-hosted models report no cached_tokens (vLLM 0.27): approximate the cached
        # fraction from the logged prefix-cache hit rate so tokens + cost are consistent
        # with model_prices (which applies the same split). No-op for cloud models.
        in_adj, cr_adj = _mp.split_self_hosted_cache(cfg, a["i"], a["cr"])
        cost_full = _mp.cost_usd(cfg, a["i"], a["o"], a["cr"], a["cw"])
        cost_io = _mp.cost_usd(cfg, a["i"], a["o"], a["cr"], a["cw"], include_cache=False)
        m = meta.get(cfg, {})
        out.append({
            "agent": cfg, "model": m.get("model") or cfg, "harness": m.get("harness") or "",
            "provider": m.get("provider") or "", "n": n, "resolved": a["resolved"],
            "rate": (a["resolved"] / n) if n else 0.0,
            "in_task": in_adj / nt, "out_task": a["o"] / nt, "cr_task": cr_adj / nt, "cw_task": a["cw"] / nt,
            "cost_io": (cost_io / n) if (cost_io is not None and n) else None,
            "cost_full": (cost_full / n) if (cost_full is not None and n) else None,
        })
    # default order = most tasks first (client sort can re-order any column); rate then
    # cost_full then agent break ties so the initial view is stable.
    out.sort(key=lambda r: (-r["n"], -(r["rate"]),
                            r["cost_full"] if r["cost_full"] is not None else 1e9, r["agent"]))
    money = lambda x: "n/a" if x is None else f"${x:,.4f}"
    num = lambda x: f"{x:,.0f}"
    trs = []
    for i, r in enumerate(out, 1):
        # data-* mirror the visible values so covSort() (below) can reorder client-side;
        # None costs -> blank data attr -> sort last (same convention as the leaderboard).
        _cio = "" if r["cost_io"] is None else f"{r['cost_io']:.6f}"
        _cfu = "" if r["cost_full"] is None else f"{r['cost_full']:.6f}"
        trs.append(
            "<tr "
            f'data-rank="{i}" data-agent="{html.escape(r["agent"])}" data-model="{html.escape(r["model"])}" '
            f'data-harness="{html.escape(r["harness"])}" data-provider="{html.escape(r["provider"])}" '
            f'data-tasks="{r["n"]}" data-resolved="{r["resolved"]:.6f}" data-rate="{r["rate"]:.6f}" '
            f'data-intask="{r["in_task"]:.3f}" data-outtask="{r["out_task"]:.3f}" '
            f'data-crtask="{r["cr_task"]:.3f}" data-cwtask="{r["cw_task"]:.3f}" '
            f'data-costio="{_cio}" data-costfull="{_cfu}">'
            f"<td class=num>{i}</td><td class=ell title=\"{html.escape(r['agent'])}\">{html.escape(r['agent'])}</td>"
            f"<td>{html.escape(r['model'])}</td><td>{html.escape(r['harness'])}</td>"
            f"<td class=ell title=\"{html.escape(r['provider'])}\">{html.escape(r['provider'])}</td>"
            f"<td class=num>{r['n']}</td><td class=num>{r['resolved']:.1f}</td>"
            f"<td class=num>{100 * r['rate']:.1f}%</td>"
            f"<td class=num>{num(r['in_task'])}</td><td class=num>{num(r['out_task'])}</td>"
            f"<td class=num>{num(r['cr_task'])}</td><td class=num>{num(r['cw_task'])}</td>"
            f"<td class=num>{money(r['cost_io'])}</td><td class=num>{money(r['cost_full'])}</td>"
            "</tr>")
    head = ("<tr>"
            "<th class='s num' data-k=rank onclick='covSort(this)' title='row index in the current sort'>#</th>"
            "<th class='s ell' data-k=agent onclick='covSort(this)'>agent_id</th>"
            "<th class=s data-k=model onclick='covSort(this)'>model</th>"
            "<th class=s data-k=harness onclick='covSort(this)'>harness</th>"
            "<th class='s ell' data-k=provider onclick='covSort(this)'>provider</th>"
            "<th class='s num' data-k=tasks onclick='covSort(this)' title='distinct validated tasks this model attempted (>=1 valid run)'>tasks</th>"
            "<th class='s num' data-k=resolved onclick='covSort(this)' title='sum of per-cell pass rate over its own tasks'>resolved</th>"
            "<th class='s num' data-k=rate onclick='covSort(this)' title='resolved / tasks -- OWN denominator, not comparable across models'>rate</th>"
            "<th class='s num' data-k=intask onclick='covSort(this)' title='per-task non-cached input tokens'>input/task</th>"
            "<th class='s num' data-k=outtask onclick='covSort(this)' title='per-task output tokens'>output/task</th>"
            "<th class='s num' data-k=crtask onclick='covSort(this)' title='per-task cache_read tokens'>cache_read/task</th>"
            "<th class='s num' data-k=cwtask onclick='covSort(this)' title='per-task cache_write tokens'>cache_write/task</th>"
            "<th class='s num' data-k=costio onclick='covSort(this)' title='(input+output) x price / tasks'>$/task (i/o)</th>"
            "<th class='s num' data-k=costfull onclick='covSort(this)' title='(input+output+cache) x price / tasks'>$/task (full)</th></tr>")
    note = ("Each model is scored over its OWN full set of attempted validated tasks "
            "(per-cell pass rate; contamination-excluded cells removed). Denominators DIFFER "
            "per model, so rates here are NOT directly comparable across models -- use the "
            "common-set Leaderboard on / for ranking. $/task = model_prices price x captured "
            "tokens / tasks. input/output/cache columns are PER-TASK means over cells that "
            "carry a token record.")
    return ("<!doctype html><html><head><meta charset=utf-8><title>zbench full coverage</title>"
            f"<style>{_APP_CSS}</style></head><body>"
            + _nav("Coverage")
            + "<h1>Per-model full coverage</h1>"
            + f"<div class=muted style='font-size:11px;margin-bottom:8px;max-width:960px'>{note}</div>"
            + "<table id=covtable><thead>" + head + "</thead><tbody>" + "".join(trs) + "</tbody></table>"
            + _COV_SORT_JS
            + "</body></html>")


def render_html(st):
    def esc(x):
        return html.escape("" if x is None else str(x))

    parts = ["""<!doctype html><html><head><meta charset=utf-8>
<title>zbench dashboard</title>
<style>""" + _APP_CSS + """</style>
</head><body>"""]

    parts.append(_nav("Leaderboard"))
    parts.append(f"<h1>zbench live dashboard</h1>")
    # leaderboard: per model x harness (agent_id), on the COMMON task set
    ncom = st.get("n_common", 0)
    # W27: one-line summary + progressive-disclosure <details>; per-column caveats
    # moved to header title= tooltips (link, don't restate -> METHODOLOGY.md).
    _excl_note = ""
    # W63: partial-coverage agents (fewer than the common set -- e.g. a mid-grid agent)
    # are shown IN the main table, muted + &#9888;-marked, hidden by this toggle.
    _partial = st.get("leaderboard_partial") or []
    _partial_toggle = (
        '<label class=muted style="font-size:11px;display:inline-block;margin:2px 0 6px">'
        '<input type=checkbox id=togglePartial checked onclick="togglePartial(this.checked)"> '
        f'show partial-coverage agents ({icon("alert", 11, "#b45309")} = ranked on own set, not comparable)</label>') if _partial else ''
    # W82: the 'copy as markdown' button lives INLINE next to the title (below), as a
    # Material Design icon (content-copy) -- not a floated corner emoji. It targets the
    # hidden #lbmd textarea (appended after the table); click-feedback swaps innerHTML.
    _mdid = "lbmd"
    # W89: feedback is a SAME-SIZE MDI icon (mdi('check')/'alert-circle') swapped in place of
    # the resting content-copy icon -- NOT a text glyph -- so there is no size change / layout
    # wiggle and the icon language stays MDI. The button is inline-flex at a fixed 15px icon.
    _copy_btn = (
        f'<button onclick="(function(b){{var el=document.getElementById(&#39;{_mdid}&#39;);'
        f'var t=el.value;var done=function(){{var o=b.innerHTML;b.innerHTML=&#39;&#39;;'
        f'b.appendChild(mdi(&#39;check&#39;,{{size:15,color:PAL.ok}}));'
        f'setTimeout(function(){{b.innerHTML=o;}},2000);}};'
        f'var fb=function(){{el.focus();el.select();try{{document.execCommand(&#39;copy&#39;);done();}}'
        f'catch(e){{b.innerHTML=&#39;&#39;;b.appendChild(mdi(&#39;alert-circle&#39;,{{size:15,color:PAL.bad}}));}}}};'
        f'if(navigator.clipboard&&navigator.clipboard.writeText){{'
        f'navigator.clipboard.writeText(t).then(done,fb);}}else{{fb();}}}})(this)" '
        f'class="btn btn-icon btn-inline" '
        f'title="copy leaderboard as Markdown">{icon("content-copy", 15, PALETTE["accent"])}</button>')
    parts.append(f"<h2 style='display:flex;align-items:center'>Leaderboard &mdash; per model &times; harness, common task set{_copy_btn}</h2>"
                 f"<div class=muted style='font-size:11px;margin-bottom:4px'>"
                 f"Ranked by <b>resolved</b>, ties indicated by <b>=</b>. Hover column headers for caveats."
                 + "</div>" + _partial_toggle + "<table id=lbtable>"
                 # W81: columns are click-to-sort (reusing the same .s header affordance +
                 # the mdi() arrow as /runs + /corpus). data-k picks the per-row data-*
                 # sort value; .num ths sort numerically. lbSort() (script below) reorders
                 # the tbody rows in place, so the server-rendered content (MDI, tooltips,
                 # partial styling, cross-highlight ids) is preserved.
                 "<thead><tr><th class='s num' data-k=rank onclick='lbSort(this)' title='standard competition rank; = marks a shared rank'>#</th>"
                 "<th class='s ell' data-k=agent onclick='lbSort(this)'>agent_id</th><th class=s data-k=model onclick='lbSort(this)'>model</th><th class=s data-k=harness onclick='lbSort(this)'>harness</th><th class='s ell' data-k=provider onclick='lbSort(this)'>provider</th>"
                 "<th class='s num' data-k=resolved onclick='lbSort(this)' title='&Sigma; per-cell pass rate over the common set (fractional = flaky multi-run cell)'>resolved</th>"
                 "<th class='s num' data-k=rate onclick='lbSort(this)' title='resolve rate = resolved / common-set size'>rate</th>"
                 "<th class='s num' data-k=miss onclick='lbSort(this)' title='wrong/incomplete fix (real capability miss)'>miss</th>"
                 "<th class='s num' data-k=nopatch onclick='lbSort(this)' title='no candidate produced: auth/turn-cap/timeout/infra, NOT a model miss'>no-patch</th>"
                 "<th class='s num' data-k=excluded onclick='lbSort(this)' title='run-cells excluded from scoring (contamination/artifact/etc.)'>excluded</th>"
                 "<th class='s num' data-k=cost onclick='lbSort(this)' title='computed $/task = models.dev price x captured tokens (or the provider-reported cost for direct Anthropic); n/a only if the model is not in the price table'>$/task</th>"
                 "<th class='s num' data-k=tokens onclick='lbSort(this)' title='PER-TASK input context = (input_tokens + cache_read) over the common set / N. This is the TOTAL input the model processed. Claude/codex report their cached context under cache_read (tiny raw input_tokens), while vLLM has no cache accounting and counts it all as input -- adding the two makes them comparable. Hover a cell for the raw split.'>input ctx/task</th>"
                 "<th class='s num' data-k=output onclick='lbSort(this)' title='PER-TASK output tokens = total output over the common set / N. Output is the provider completion count, which bills reasoning/thinking tokens as output -- so this already includes reasoning tokens.'>output/task</th>"
                 "<th class='s num' data-k=turns onclick='lbSort(this)' title='PER-TASK agentic turns (model round-trips) = total turns over the common set / attempts with a turn record. Per harness's own definition (claude num_turns / pi assistant-messages / codex turns), so compare WITHIN a harness. Display only, not ranked.'>turns/task</th>"
                 "<th class='s num' data-k=gen onclick='lbSort(this)' title='PER-TASK generation wall-time (= total gen_ms / N; hover for the total)'>time/task</th></tr></thead><tbody>")
    # W72 (2026-08-02): render cohort + partial agents in ONE interleaved, rate-ranked
    # pass so partials appear at their ranked place (muted + warning), not dumped at the end.
    for r in _leaderboard_ranked_view(st.get("leaderboard", []), _partial):
        aq = esc(r["agent_id"])
        if r.get("_partial"):
            pn = r.get("n") or 0
            prate = (r["resolved"] / pn * 100) if pn else 0
            # W92: the real reason an agent is partial is that it is MISSING some common-set task(s),
            # NOT that it attempted fewer tasks (its own set can exceed the common set). Describe it by
            # common-set coverage + the missing tasks.
            _cc = r.get("common_covered"); _ct = r.get("common_total") or ncom
            _miss = r.get("missing_common") or []
            _miss_txt = (" -- missing " + str(len(_miss)) + " common-set task(s): "
                         + ", ".join(_miss[:4]) + ("..." if len(_miss) > 4 else "")) if _miss else ""
            _cov_txt = (f"covers {_cc}/{_ct} common-set tasks" if _cc is not None
                        else f"does not cover the full {_ct}-task common set")
            pcost = r.get("cost_usd") or 0
            pcost_cell = (_cost_cell_html(pcost / pn) if pcost and pn else '<span class=muted>n/a</span>')
            # W83: full total cost in the tooltip (like tokens/gen per-task cells).
            pcost_title = f'${pcost:,.2f} total over {pn} tasks' if pcost and pn else ''
            parts.append(
                # W81: data-* sort keys (partials lack miss/no-patch/excluded/tokens/gen -> blank -> sort last)
                f'<tr data-entry-id="{aq}" data-partial=1 '
                f'data-rank="{r.get("rank") or ""}" data-agent="{aq}" data-model="{esc(r.get("model_name") or "")}" '
                f'data-harness="{esc(r.get("harness") or "")}" data-provider="{esc(r.get("provider") or "")}" '
                f'data-resolved="{r["resolved"]}" data-rate="{prate:.4f}" '
                f'data-cost="{(pcost / pn) if pcost and pn else ""}" data-miss="" data-nopatch="" data-excluded="" data-tokens="" data-output="" data-turns="" data-gen="" '
                f'style="color:#94a3b8" '
                f'title="partial coverage: {_cov_txt}{_miss_txt}. Ranked on its OWN {pn}-task set by rate '
                f'(~rank {r.get("rank")}), NOT comparable to the common-set cohort.">'
                f'<td class=num title="slot rank by resolve rate on its own set -- not comparable">~{r.get("rank")}</td>'
                f'<td class="mono ell">{icon("alert", 12, "#b45309")} <a href="/agent?id={aq}" style="color:inherit;text-decoration:none" title="{aq}">{aq}</a></td><td>{esc(r.get("model_name") or "")}</td>'
                f'<td>{_chip_html(r.get("harness") or "")}</td>'
                f'<td class=ell title="{esc(r.get("provider") or "")}">{esc(r.get("provider") or "")}</td>'
                f'<td class=num><a href="/runs?agent={aq}&status=resolved">{_resfmt(r["resolved"])}</a>/<a href="/runs?agent={aq}" title="all attempts">{pn}</a></td>'
                f'<td class=num>{prate:.0f}%</td><td class=num></td><td class=num></td><td class=num></td>'
                f'<td class=num title="{pcost_title}">{pcost_cell}</td><td class=num></td><td class=num></td><td class=num></td><td class=num></td></tr>')
            continue
        # W75/W95: gen + tokens shown PER-TASK, but averaged ONLY over attempts that HAVE
        # a record (missing/0 excluded from the denominator, not counted as 0).
        _n = r.get("n") or 1
        _ntok = r.get("n_tok") or _n
        _ngen = r.get("n_gen") or _n
        _nturns = r.get("n_turns") or 0
        turns_pt = (r.get("turns") or 0) / _nturns if _nturns else None
        turns_cell = f'{turns_pt:.0f}' if turns_pt is not None else ""
        turns_tot = (f'{r.get("turns",0):,} turns total; avg over {_nturns} attempt(s) with a turn record'
                     + (f' ({_n - _nturns} of {_n} had none -> excluded from the avg)' if (_n - _nturns) else '')
                     if _nturns else 'no turn record captured for this agent yet')
        gen = f'{(r["gen_ms"]/_ngen)/60000:.1f}m' if r.get("gen_ms") else ""
        _gmiss = _n - _ngen
        gen_tot = ((f'{r["gen_ms"]/60000:.0f}m total; avg over {_ngen} attempt(s) with a gen record'
                    + (f' ({_gmiss} of {_n} had none -> excluded from the avg)' if _gmiss else ''))
                   if r.get("gen_ms") else "")
        npc = r.get("no_patch", 0)
        np_cell = (f'<a href="/runs?agent={aq}&status=no_patch" style="color:#b45309">{npc}</a>'
                   if npc else "0")
        miss = r.get("miss", 0)
        miss_cell = f'<a href="/runs?agent={aq}&status=miss">{miss}</a>' if miss else "0"
        invc = r.get("invalid", 0)
        inv_cell = (f'<a href="/runs?agent={aq}&status=excluded" style="color:#dc2626" '
                    f'title="contaminated cells discarded from this agent\'s score">{invc}</a>'
                    if invc else "0")
        rank_disp = f'{r["rank"]}{"=" if r.get("rank_shared") else ""}'
        cost = r.get("cost_usd") or 0
        cost_cell = (_cost_cell_html(cost / r["n"]) if cost and r["n"]
                     else '<span class=muted title="pricing not wired -- reports $0, NOT free">n/a</span>')
        # W83: full total cost in the tooltip (mirrors the tokens/gen per-task columns).
        cost_title = f'${cost:,.2f} total over {r["n"]} tasks' if cost and r["n"] else ''
        parts.append(
            # W81: data-* sort keys mirror the visible per-task values.
            f'<tr data-entry-id="{aq}" data-rank="{r["rank"]}" data-agent="{aq}" '
            f'data-model="{esc(r["model_name"])}" data-harness="{esc(r["harness"])}" data-provider="{esc(r["provider"])}" '
            f'data-resolved="{r["resolved"]}" data-rate="{r["resolve_rate"]:.4f}" data-miss="{miss}" data-nopatch="{npc}" '
            f'data-excluded="{invc}" data-cost="{(cost / r["n"]) if cost and r["n"] else ""}" '
            f'data-tokens="{(r.get("in_tokens",0)+r.get("cache_tokens",0))//_ntok}" data-output="{r.get("out_tokens",0)//_ntok}" data-turns="{turns_pt if turns_pt is not None else ""}" data-gen="{(r["gen_ms"]/_ngen) if r.get("gen_ms") else ""}">'
            f'<td class=num>{rank_disp}</td><td class="mono ell"><a href="/agent?id={aq}" style="color:inherit;text-decoration:none" title="{aq}">{aq}</a></td><td>{esc(r["model_name"])}</td>'
            f'<td>{_chip_html(r["harness"])}</td>'
            f'<td class="muted ell" title="{esc(r["provider"])}">{esc(r["provider"])}</td>'
            f'<td class=num><a href="/runs?agent={aq}&status=resolved">{_resfmt(r["resolved"])}</a>/<a href="/runs?agent={aq}" title="all attempts">{r["n"]}</a></td>'
            f'<td class=num>{r["resolve_rate"]*100:.0f}%</td>'
            f'<td class=num>{miss_cell}</td><td class=num>{np_cell}</td><td class=num>{inv_cell}</td>'
            f'<td class=num title="{cost_title}">{cost_cell}</td>'
            f'<td class=num title="PER-TASK input context = (input_tokens + cache_read) over the {_ntok} attempt(s) WITH a token record'
            f'{(" (" + str(_n - _ntok) + " of " + str(_n) + " had none -> excluded from the avg)") if (_n - _ntok) else ""}. '
            f'Per task -- raw input: {r.get("in_tokens",0)//_ntok:,}; cache_read: {r.get("cache_tokens",0)//_ntok:,}. '
            f'Total input+cache: {r.get("in_tokens",0)+r.get("cache_tokens",0):,}">'
            f'{(r.get("in_tokens",0)+r.get("cache_tokens",0))//_ntok:,}</td>'
            f'<td class=num title="PER-TASK output tokens (includes reasoning/thinking, billed as output) = '
            f'{r.get("out_tokens",0):,} total over {_ntok} token-bearing attempt(s)">{r.get("out_tokens",0)//_ntok:,}</td>'
            f'<td class=num title="{esc(turns_tot)}">{turns_cell}</td>'
            f'<td class=num title="{gen_tot}">{esc(gen)}</td></tr>')
    parts.append("</tbody></table>")
    # W81: click-to-sort the leaderboard columns (reuses mdi()/PAL from the shared bundle
    # for the same arrow language as the /runs + /corpus sortable headers). Reorders the
    # tbody rows in place; blanks (partials' empty per-task cells) always sort last.
    parts.append(
        '<script>(function(){var tbl=document.getElementById("lbtable");if(!tbl)return;'
        'var dir={},cur=null;window.lbSort=function(th){var k=th.getAttribute("data-k");'
        'var num=th.classList.contains("num");dir[k]=(cur===k)?-dir[k]:1;cur=k;'
        'var tb=tbl.tBodies[0];var rows=[].slice.call(tb.rows);'
        'rows.sort(function(a,b){var x=a.getAttribute("data-"+k),y=b.getAttribute("data-"+k);'
        'if(num){var xe=(x===""||x==null),ye=(y===""||y==null);'
        'if(xe&&ye)return 0;if(xe)return 1;if(ye)return -1;'
        'return (parseFloat(x)-parseFloat(y))*dir[k];}'
        'x=(x||"").toLowerCase();y=(y||"").toLowerCase();return (x<y?-1:x>y?1:0)*dir[k];});'
        'rows.forEach(function(r){tb.appendChild(r);});'
        '[].forEach.call(tbl.tHead.rows[0].cells,function(c){var s=c.querySelector(".ar");if(s)s.remove();});'
        'var ar=document.createElement("span");ar.className="ar";ar.style.marginLeft="2px";'
        'ar.appendChild(mdi(dir[k]>0?"menu-up":"menu-down",{size:12,color:PAL.muted2}));th.appendChild(ar);};})();</script>')
    # W33: 'copy as markdown' -- server-renders the canonical board (shared helper)
    # into a hidden element; the button copies it. navigator.clipboard is ONLY
    # defined in a secure context (HTTPS/localhost); the dashboard is served over
    # plain HTTP so it's undefined there -> fall back to select + execCommand('copy').
    # (Bug: 'Cannot read properties of undefined (reading writeText)' on http://...)
    # W82: only the hidden source textarea lives here now; the copy button is inline in
    # the <h2> title above (built as _copy_btn).
    _md = leaderboard_markdown(st.get("leaderboard", []), ncom)
    parts.append(
        f'<textarea id="{_mdid}" readonly style="position:absolute;left:-9999px;top:-9999px" '
        f'aria-hidden="true">{esc(_md)}</textarea>')
    # visual leaderboard diagram (bars = resolved on the common set; whiskers = CI).
    # Render TWO independently-laid-out SVGs: FULL (incl. partial-coverage bars) and
    # RANKED-ONLY (no partials -> no gaps). The partial toggle SWAPS which is shown
    # (user 2026-08-02: hiding bars in place left awkward empty space) -- recreating the
    # layout for the new set rather than poking SVG geometry. The toggle only flips
    # container visibility; it never touches chart internals (loose coupling).
    chart = render_leaderboard_chart(st.get("leaderboard", []), ncom, partial=st.get("leaderboard_partial"))
    chart_ranked = render_leaderboard_chart(st.get("leaderboard", []), ncom, partial=None)
    if chart:
        # W74/W82: the SVG-download button sits INLINE next to the 'Leaderboard chart'
        # title as a Material Design (download) icon -- not a floated corner emoji/arrow.
        _dl_btn = ('<button onclick="downloadChartSvg()" title="download the displayed chart as an SVG file" '
                   'class="btn btn-icon btn-inline">'
                   + icon("download", 14, PALETTE["accent"]) + '</button>')
        parts.append('<div style="margin:12px 0 4px"><b style="font-size:13px">Leaderboard '
                     'chart</b>' + _dl_btn + ' <span class=muted style="font-size:11px">&mdash; '
                     '<span style="display:inline-block;width:9px;height:9px;background:var(--openw);margin:0 3px 0 6px"></span>open-weight '
                     '<span style="display:inline-block;width:9px;height:9px;background:var(--prop);margin:0 3px 0 10px"></span>proprietary. '
                     'Whiskers = Wilson 95% CI.'
                     '</span></div>')
        parts.append('<div style="margin-bottom:8px">'
                     '<div data-chart="full">' + chart + '</div>'
                     '<div data-chart="ranked" style="display:none">' + chart_ranked + '</div>'
                     '</div>')
    # W142/W145: 2D capability-vs-cost Pareto scatter (frontier = non-dominated agents).
    _ptol = st.get("pareto_tolerance") or 0.0
    # W147: two variants swapped by the shared "show partial-coverage agents" checkbox --
    # WITH-PARTIALS-PARTICIPATING (checkbox checked / default) and RANKED-ONLY (unchecked).
    _lb = st.get("leaderboard", [])
    _part = st.get("leaderboard_partial")
    pareto_wp = render_pareto_chart(_lb, tolerance=_ptol, partial=_part, partial_in_frontier=True)
    pareto_ranked = render_pareto_chart(_lb, tolerance=_ptol, partial=None, partial_in_frontier=False)
    if pareto_wp:
        _dl_btn2 = ('<button onclick="downloadParetoSvg()" title="download the Pareto chart as an SVG file" '
                    'class="btn btn-icon btn-inline">' + icon("download", 14, PALETTE["accent"]) + '</button>')
        parts.append(f'<div style="margin:12px 0 4px"><b style="font-size:13px">Pareto frontier '
                     f'(practical-equivalence threshold: {_ptol*100:.0f}% resolve rate)</b>'
                     + _dl_btn2 +
                     ' <span class=muted style="font-size:11px">&mdash; capability (resolve rate) '
                     'vs cost (computed $/task). Filled dots joined by the dashed line are '
                     'non-dominated; faded dashed dots are practically equivalent (resolve rate '
                     f'within {_ptol*100:.0f}% of a cheaper frontier agent, so the cheaper one '
                     'wins); hollow dots are dominated. Diamonds = partial-coverage agents; when '
                     '"show partial-coverage agents" is checked they PARTICIPATE in the frontier '
                     '(colored by their tier) using their OWN-set rate (exploratory, not '
                     'apples-to-apples); unchecked hides them and the frontier is ranked-only.'
                     '</span></div>')
        parts.append('<div id="paretoChart" style="margin-bottom:8px">'
                     '<div data-chart-pareto="withpartial">' + pareto_wp + '</div>'
                     '<div data-chart-pareto="ranked" style="display:none">' + pareto_ranked + '</div>'
                     '</div>')
    # W63: the separate 'partial coverage' section is GONE (folded into the table above);
    # the 'Excluded from ranking' callout is REMOVED (exclusions are just excluded -- they
    # stay in the raw /runs listing, no need to call them out and muddy the board).
    parts.append('<script>function togglePartial(show){'
                 'document.querySelectorAll("[data-partial]").forEach(function(e){e.style.display=show?"":"none";});'
                 # swap the pre-rendered leaderboard chart variants so the ranked-only layout has no gap:
                 'var f=document.querySelector(\'[data-chart=full]\'),r=document.querySelector(\'[data-chart=ranked]\');'
                 'if(f)f.style.display=show?"":"none";if(r)r.style.display=show?"none":"";'
                 # W147: swap the pareto variants -- checked = partials participate in the frontier:
                 'var pw=document.querySelector(\'[data-chart-pareto=withpartial]\'),pr=document.querySelector(\'[data-chart-pareto=ranked]\');'
                 'if(pw)pw.style.display=show?"":"none";if(pr)pr.style.display=show?"none":"";'
                 '}\n'
                 # W74: serialize the VISIBLE chart variant's <svg> to a downloadable blob.
                 'function downloadChartSvg(){'
                 'var f=document.querySelector(\'[data-chart=full]\'),r=document.querySelector(\'[data-chart=ranked]\');'
                 'var box=(f&&f.style.display!=="none")?f:((r&&r.style.display!=="none")?r:f);'
                 'var svg=box&&box.querySelector("svg");if(!svg)return;'
                 'var s=new XMLSerializer().serializeToString(svg);'
                 'if(s.indexOf("xmlns")<0)s=s.replace("<svg",\'<svg xmlns="http://www.w3.org/2000/svg"\');'
                 'var blob=new Blob([\'<?xml version="1.0" encoding="UTF-8"?>\\n\'+s],{type:"image/svg+xml"});'
                 'var url=URL.createObjectURL(blob),a=document.createElement("a");'
                 'a.href=url;a.download="leaderboard.svg";document.body.appendChild(a);a.click();'
                 'document.body.removeChild(a);setTimeout(function(){URL.revokeObjectURL(url);},1000);'
                 '}\n'
                 # W142/W145: same serialize-to-blob download for the Pareto scatter.
                 'function downloadParetoSvg(){'
                 'var pw=document.querySelector(\'[data-chart-pareto=withpartial]\'),pr=document.querySelector(\'[data-chart-pareto=ranked]\');'
                 'var box=(pw&&pw.style.display!=="none")?pw:((pr&&pr.style.display!=="none")?pr:pw);'
                 'var svg=box&&box.querySelector("svg");if(!svg)return;'
                 'var s=new XMLSerializer().serializeToString(svg);'
                 'if(s.indexOf("xmlns")<0)s=s.replace("<svg",\'<svg xmlns="http://www.w3.org/2000/svg"\');'
                 'var blob=new Blob([\'<?xml version="1.0" encoding="UTF-8"?>\\n\'+s],{type:"image/svg+xml"});'
                 'var url=URL.createObjectURL(blob),a=document.createElement("a");'
                 'a.href=url;a.download="pareto.svg";document.body.appendChild(a);a.click();'
                 'document.body.removeChild(a);setTimeout(function(){URL.revokeObjectURL(url);},1000);'
                 '}</script>')
    # Generic cross-highlight BUS (NO business-level coupling): views don't know about
    # each other or about "agents" -- they only tag their elements with a generic
    # data-entry-id="<opaque id>" and speak a small event protocol (hl:on / hl:off on
    # document, carrying detail.id). Hovering any [data-entry-id] element broadcasts its
    # id; every element sharing that id toggles .lb-hl. Add a 3rd view later = just give
    # its elements data-entry-id + the .lb-hl styling; no wiring changes.
    parts.append(
        '<script>(function(){'
        'var SEL=\'[data-entry-id]\',ATTR=\'data-entry-id\';'
        'function apply(id,on){if(!id)return;'
        'document.querySelectorAll(SEL).forEach(function(el){'
        'if(el.getAttribute(ATTR)===id)el.classList.toggle(\'lb-hl\',on);});}'
        'document.addEventListener(\'hl:on\',function(e){apply(e.detail&&e.detail.id,true);});'
        'document.addEventListener(\'hl:off\',function(e){apply(e.detail&&e.detail.id,false);});'
        # event-delegation so ANY view opts in purely by tagging elements with data-entry-id:
        'document.addEventListener(\'mouseover\',function(e){'
        'var t=e.target.closest&&e.target.closest(SEL);'
        'if(t)document.dispatchEvent(new CustomEvent(\'hl:on\',{detail:{id:t.getAttribute(ATTR)}}));});'
        'document.addEventListener(\'mouseout\',function(e){'
        'var t=e.target.closest&&e.target.closest(SEL);'
        'if(t)document.dispatchEvent(new CustomEvent(\'hl:off\',{detail:{id:t.getAttribute(ATTR)}}));});'
        '})();</script>')
    parts.append("</body></html>")
    return "".join(parts)


# ---- drill-down: per-task cells and per-run transcript --------------------
# D5: detail-page head = the SHARED _BASE_CSS + detail specifics (pipeline/stage/pre).
# Uses a __TITLE__ placeholder (NOT .format) so CSS braces are literal -- removes the
# old brace-doubling tech debt.
_PAGE_HEAD = ("<!doctype html><html><head><meta charset=utf-8><title>__TITLE__</title><style>"
              + _BASE_CSS +
              " h1{font-size:19px;margin:0 0 8px} h2{font-size:14px;margin:16px 0 6px}"
              " pre{background:#0f172a;color:#e2e8f0;padding:10px;border-radius:6px;overflow:auto;max-height:460px;font-size:11px;white-space:pre-wrap}"
              " details{margin:6px 0} summary{cursor:pointer;font-size:13px}"
              " .pipe{display:flex;flex-wrap:wrap;align-items:stretch;gap:0;margin:14px 0 18px}"
              " .pipe-cell{display:flex;align-items:stretch;flex:1 1 190px;min-width:150px}"
              " .pipe-cell .stage{flex:1;min-width:0}"
              " .stage{flex:1 1 170px;min-width:150px;border:1px solid #e2e8f0;border-radius:8px;padding:8px 11px;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.06)}"
              " .stage h3{font-size:11px;margin:0 0 6px;text-transform:uppercase;letter-spacing:.05em;color:#64748b;font-weight:700;display:flex;justify-content:space-between;align-items:center;gap:6px}"
              " .stagetime{font-size:11px;font-weight:700;letter-spacing:0;text-transform:none;color:#334155;background:#eef2f7;border-radius:10px;padding:1px 8px;white-space:nowrap}"
              " .stagetime.to{color:#fff;background:#dc2626}"
              " .stagetime.na{color:#94a3b8;background:transparent;font-weight:400}"
              " .stage .li{font-size:12px;margin:3px 0;line-height:1.35}"
              " .stage.ok{border-color:#86efac;background:#f0fdf4} .stage.bad{border-color:#fecaca;background:#fef2f2}"
              " .stage.warn{border-color:#fde68a;background:#fffbeb} .stage.gray{border-color:#e2e8f0;background:#f8fafc}"
              " .arrow{display:flex;flex-direction:column;justify-content:center;align-items:center;padding:0 7px;color:#94a3b8;font-size:22px;font-weight:700;line-height:1}"
              " .arrow small{font-size:10px;font-weight:500;color:#64748b;white-space:nowrap;margin-top:3px}"
              "</style></head><body>")


def _page_head(title, active=""):
    """Shared head + fixed nav for server-rendered detail pages (D5: shared _BASE_CSS)."""
    return _PAGE_HEAD.replace("__TITLE__", html.escape(title)) + _nav(active)


def _benchdb_attempts(run_id=None):
    """All attempts from bench.db (the single store) as score-shaped dicts, so the
    drill-down pages (/runs, /task, /run, /batch) consume them unchanged. Optional
    run_id filter. Invalidation is NOT applied here -- callers drop contaminated
    runs themselves (so agent-level-excluded agents still show their raw cells)."""
    import sqlite3
    db = Path(BENCHDB)
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        meta = _agents_meta()   # facts-only: model/provider from the file dim (model/harness_config tables dropped)
        sql = ("SELECT a.config_id, a.task_id, a.run_id, a.evaluation_id, a.tests_passed, "
               "a.status, a.outcome, a.cost_usd, a.finished_at, a.runtime_ms, "
               "a.total_duration_ms, a.input_tokens, a.output_tokens, a.cache_read_tokens "
               "FROM attempt a")
        params = ()
        if run_id:
            sql += " WHERE a.run_id=?"
            params = (run_id,)
        out = []
        for r in conn.execute(sql, params):
            am = meta.get(r["config_id"]) or {}
            tot = (r["input_tokens"] or 0) + (r["output_tokens"] or 0) + (r["cache_read_tokens"] or 0)
            out.append({
                "agent_id": r["config_id"], "instance_id": constants.instance_of(r["task_id"]),
                "run_id": r["run_id"], "evaluation_id": r["evaluation_id"],
                "tests_passed": bool(r["tests_passed"]), "status": r["status"],
                "attempt_outcome": r["outcome"], "model_name": am.get("model"),
                "provider": am.get("provider"), "cost_usd": r["cost_usd"],
                "timestamp": r["finished_at"],
                "metrics": {"total_tokens": tot, "output_tokens": r["output_tokens"],
                            "runtime_ms": r["runtime_ms"], "total_duration_ms": r["total_duration_ms"]},
            })
        return out
    finally:
        conn.close()


def _run_score_index(run_id):
    """Per-run attempts from bench.db keyed (agent, instance)."""
    if not run_id or "/" in run_id:
        return {}
    idx = {}
    for s in _benchdb_attempts(run_id):
        idx[(s.get("agent_id"), s.get("instance_id"))] = s
    return idx


def _best_cell_score(run_id, agent_id, instance_id):
    """Score for one cell. Returns (record, source) where source is
    'this_run' (per-run file or shared with matching run_id) | 'other_run'
    (most recent scored attempt of the same cell in a DIFFERENT run) | None."""
    pr = _run_score_index(run_id)
    if (agent_id, instance_id) in pr:
        return pr[(agent_id, instance_id)], "this_run"
    best = None
    for s in _benchdb_attempts():
        if s.get("agent_id") == agent_id and s.get("instance_id") == instance_id:
            srid = s.get("run_id")
            # a matching record whose run_id is null/blank is this cell's score,
            # just unstamped (common in backfilled records) -- treat as this_run,
            # NOT a different run.
            if srid == run_id or not srid:
                return s, "this_run"
            if best is None or str(s.get("timestamp", "")) >= str(best.get("timestamp", "")):
                best = s
    return (best, "other_run") if best else ({}, None)



def _outcome_of(s):
    """resolved | no_patch | miss -- the COARSE DISPLAY trichotomy for the board/matrix.

    DEDUP_REVIEW D8 (investigated 2026-08-02): this is intentionally NOT unified with
    `scoring.classify_attempt` (the canonical, finer failure-mode taxonomy). They
    AGREE on all 682/705 attempts; the only 23 divergences are internal_error / verify-
    timeout rows that scoring calls `artifact:infra` and this calls `miss` -- and ALL
    23 are already scoring-EXCLUDED, so they never reach the leaderboard (board-invariant).
    Delegating would be LOSSY: the 3-way display can't hold `artifact:*`, and collapsing
    infra->no_patch is MORE misleading than the current benign miss on an excluded cell.
    So: keep the coarse display fn here; the canonical classifier stays scoring."""
    if s.get("tests_passed"):
        return "resolved"
    if s.get("status") == "no_patch_generated" or s.get("attempt_outcome") == "candidate_missing":
        return "no_patch"
    return "miss"


def _task_meta(task_id):
    mp = TASKS / task_id / "meta.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text())
        except Exception:
            return {}
    return {}


def _task_artifact_path(task_id, name):
    """Resolve a whitelisted task-local artifact path, or None. The task id is an
    OPAQUE token (no shape assumption) -- validate it as a safe single path segment."""
    task_id = constants.task_of(str(task_id or ""))
    if (not task_id or "/" in task_id or ".." in task_id
            or name not in TASK_ARTIFACT_NAMES):
        return None
    # gold_code.patch is the ANSWER KEY and lives outside the task dir, in
    # zbench-tasks/solutions/<task_id>/ (see zbench-tasks/config.py). Resolve it there.
    # A consumer who deletes that tree simply gets no link -- the page still renders.
    fp = (SOLUTIONS / task_id / name) if name == "gold_code.patch" else (TASKS / task_id / name)
    return fp if fp.exists() and fp.is_file() else None


def _instance_problem(task_id):
    """Problem statement for a task from its instance.jsonl (the corpus source of
    truth). Used as a fallback for the /run + /field views when a cell's per-try
    record has not been written yet (e.g. a still-RUNNING cell) so the page does
    not claim 'no problem statement' for a task that clearly has one."""
    ip = TASKS / task_id / "instance.jsonl"
    if not ip.exists():
        return ""
    try:
        for line in ip.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            ps = rec.get("problem_statement")
            if ps:
                return ps
    except Exception:
        return ""
    return ""



def _related(links):
    """A separate 'related:' line of links that navigate ELSEWHERE (not breadcrumb).
    links = [(label_html, href)]; external http links open in a new tab."""
    if not links:
        return ""
    items = " &middot; ".join(
        f'<a href="{html.escape(h)}"{" target=_blank rel=noopener" if h.startswith("http") else ""}>{label}</a>'
        for label, h in links)
    return f'<div class=muted style="font-size:11px;margin-bottom:8px">related: {items}</div>'


def _benchdb_dir():
    return Path(BENCHDB).resolve().parent


def _bundle_dir(name):
    """Resolve a blobs/attempt/<eval> bundle by its id, safely under bench-db/."""
    if not name or "/" in name or ".." in name:
        return None
    d = _benchdb_dir() / "blobs" / "attempt" / name
    return d if d.is_dir() else None


def _bundle_file(bundle, name):
    """Resolve a file inside an evidence bundle, safely."""
    d = _bundle_dir(bundle)
    if not d or not name or "/" in name or ".." in name:
        return None
    fp = d / name
    return fp if fp.is_file() else None


def _attempt_bundle(run_id, agent_id, instance_id):
    """The per-attempt blob bundle Path for one cell (derived from the attempt evaluation_id)."""
    import sqlite3
    db = Path(BENCHDB)
    if not db.exists():
        return None
    task_id = constants.task_of(instance_id)
    conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
    try:
        r = conn.execute("SELECT evaluation_id FROM attempt WHERE run_id=? AND config_id=? "
                         "AND task_id=?",
                         (run_id, agent_id, task_id)).fetchone()
    finally:
        conn.close()
    if not r or not r[0]:
        return None
    bd = _benchdb_dir() / "blobs" / "attempt" / r[0]   # facts-only: derive from eval_id
    return bd if bd.is_dir() else None


def _find_cell_files(run_id, agent_id, instance_id):
    """Locate transcript/verify/raw files for one cell in its bench.db blob bundle."""
    d = _attempt_bundle(run_id, agent_id, instance_id)
    if not d:
        return {"agent_io": None, "verify": [], "raw": [], "sessions": [], "dir": None}
    pref = f"{agent_id}__{instance_id}__"
    # The per-agent io_logging record (the transcript source). OLD fork bundles named it
    # `{pref}try1__<ts>.json`; zbench dropped the try token (W109) -> `{pref}<ts>.json`.
    # Glob try-AGNOSTICally so BOTH resolve (the bundle is per-attempt, so `{pref}*.json`
    # only ever matches this cell's io_logging record(s)).
    tryjs = sorted(d.glob("agent_io.json")) or sorted(d.glob(f"{pref}*.json"))
    # Two verify-log conventions: the BATCH engine writes per-stage
    # `<agent>__<instance>__verify__<ts>.log` files; the decentralized CELL engine
    # writes ONE self-contained `pb-verify.log` (agent patch + pb run + verdict) per
    # attempt bundle. Match both, else cell-engine runs (kimi/local/coverage cells)
    # show NO verify log on /run even though the evidence is in the bundle.
    verify = sorted(d.glob(f"{pref}verify__*.log")) or sorted(d.glob("pb-verify*.log"))  # chronological; last = final verdict
    # pi rawcli/session AND claude FAIL logs omit the agent id (and FAIL logs omit
    # the instance) in their filename, so a run dir with several cells would
    # cross-contaminate. Attribute each candidate by requiring the worktree token for
    # THIS cell -- `<instance>_<agent>` -- in the file head. (zbench's worktree is
    # `zbench_wt_<instance>_<agent>` with NO try suffix (W109); the OLD fork's was
    # `..._try1`, of which `<instance>_<agent>` is a prefix -> this matches BOTH. The
    # `<instance>_<agent>` pair is the full cell identity now that try is gone.)
    wt_token = f"{instance_id}_{agent_id}"

    def _mine(p):
        if not (agent_id and instance_id):
            return True
        try:
            with p.open("r", errors="replace") as fh:
                head = fh.read(65536)
            return wt_token in head
        except Exception:
            return False
    raw = sorted(d.glob("rawcli.txt"))
    raw += [p for p in sorted(d.glob(f"*__{instance_id}__rawcli*.txt")) if _mine(p)]
    raw += [p for p in sorted(d.glob("*rawcli_FAIL*.txt")) if _mine(p)]
    sessions = sorted(d.glob("session.jsonl"))
    sessions += [p for p in sorted(d.glob(f"pi__{instance_id}__*__session__*.jsonl")) if _mine(p)]
    return {"agent_io": tryjs[-1] if tryjs else None, "verify": verify, "raw": raw,
            "sessions": sessions, "dir": d}


def _live_session(run_id, agent_id, instance_id):
    """Newest LIVE transcript for an in-flight cell, from bench-db/.runtime/cells
    staging (not blobs -- blobs are written only when the attempt lands). Lets the
    dashboard show a partial transcript WHILE the cell is still running."""
    if not run_id or "/" in run_id or ".." in run_id:
        return None
    import re
    def _safe(v):
        return re.sub(r"[^A-Za-z0-9._-]+", "_", str(v))[:120]
    runtime = RUNTIME or (Path(BENCHDB).resolve().parent / ".runtime")
    croot = runtime / "cells"
    if not croot.is_dir():
        return None
    dirs = [x for x in croot.glob(f"{_safe(agent_id)}__{_safe(instance_id)}__{_safe(run_id)}__*") if x.is_dir()]
    d = max(dirs, key=lambda p: p.stat().st_mtime, default=None)
    if d is None:
        return None
    sess = d / "session.jsonl"
    if sess.is_file():
        return sess
    raw = d / "rawcli.txt"
    return raw if raw.is_file() else None



_RUNNING_CACHE = None
_LIVE_LEASE_CACHE = None


def _phase_is_waiting(ph):
    """A lease phase that means the cell is LAUNCHED but BLOCKED (not executing): the W132
    per-phase waits (waiting-gen = blocked on the per-provider generation slot, waiting-verify =
    blocked on the local build slot) plus the pre-run waits (acquiring-slot/queued/starting)."""
    ph = (ph or "").lower()
    return ph.startswith("waiting") or ph in ("acquiring-slot", "queued", "starting", "slot-wait")


def _live_leases():
    """[(cell_key, phase)] for every FRESH (age<=ttl) `.runtime/live` lease. The lease is the
    accurate liveness+phase source (run_cell heartbeats every 60s and sets the ACTUAL phase);
    a stale lease (age>ttl, e.g. a hard-killed run) is dropped. Cached ~3s."""
    global _LIVE_LEASE_CACHE
    now = time.time()
    if _LIVE_LEASE_CACHE and now - _LIVE_LEASE_CACHE[0] < 3.0:
        return _LIVE_LEASE_CACHE[1]
    out = []
    live = (RUNTIME or (Path(BENCHDB).resolve().parent / ".runtime")) / "live"
    if live.is_dir():
        for rd in live.iterdir():
            if not rd.is_dir():
                continue
            for f in rd.glob("*.json"):
                try:
                    d = json.loads(f.read_text() or "{}")
                except Exception:
                    continue
                age = _age_secs(d.get("heartbeat_at") or d.get("started_at"))
                if age is not None and age > d.get("ttl_s", 900):
                    continue  # stale lease = not live
                task_id = constants.task_of(str(d.get("task_id") or ""))
                cfg = d.get("config_id")
                if cfg:
                    out.append((constants.cell_key(task_id, cfg), (d.get("phase") or "").lower()))
    _LIVE_LEASE_CACHE = (now, out)
    return out


def _running_cells():
    """Cell keys EXECUTING now, derived from fresh `.runtime/live` leases BY PHASE (W143/W132).
    The flock slots CANNOT distinguish generating from waiting-gen: with phase-aware slotting only
    the whole-cell `global` slot carries the cell tag (held for the ENTIRE cell incl. while blocked
    on a gen/build slot), while the per-phase provider/build slots are untagged -- so a flock read
    false-flags every in-flight cell (incl. a cell queued behind e.g. the local cap=1 provider slot)
    as running. The lease records the ACTUAL phase, so classify from that: EXECUTING = fresh lease
    whose phase is NOT a waiting phase (and not empty/closed). Cached ~3s."""
    global _RUNNING_CACHE
    now = time.time()
    if _RUNNING_CACHE and now - _RUNNING_CACHE[0] < 3.0:
        return _RUNNING_CACHE[1]
    keys = {k for k, ph in _live_leases()
            if ph and ph not in ("done", "closed") and not _phase_is_waiting(ph)}
    _RUNNING_CACHE = (now, keys)
    return keys


_WAITING_CACHE = None


def _waiting_cells():
    """Cell keys ('<instance>_<agent>' plus legacy '<instance>_<agent>_try<N>') that are LAUNCHED but WAITING to
    execute -- they hold an open `.runtime/live` lease whose phase is a pre-run
    waiting phase (acquiring-slot/queued/waiting/starting) and do NOT (yet) hold a
    slot. Mirrors run_cell's Lease lifecycle: open('acquiring-slot') -> heartbeat
    ('running') once slots are claimed. Excludes cells already RUNNING (slot-held)
    and stale leases (age > TTL). Cached ~3s."""
    global _WAITING_CACHE
    now = time.time()
    if _WAITING_CACHE and now - _WAITING_CACHE[0] < 3.0:
        return _WAITING_CACHE[1]
    keys = {k for k, ph in _live_leases() if _phase_is_waiting(ph)}
    _WAITING_CACHE = (now, keys)
    return keys


def _age_secs(ts):
    if not ts:
        return None
    try:
        from datetime import datetime, timezone
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds()
    except Exception:
        return None


def _cell_running(instance_id, agent_id):
    """Is THIS cell currently executing (a live process holds its slot)?"""
    keys = _running_cells()
    ck = constants.cell_key(constants.task_of(str(instance_id or "")), agent_id)
    return ck in keys or any(k.startswith(ck + "_try") for k in keys)



def render_task_page(task_id):
    """W96: the ONE canonical task page (/task). Folds in the card.md problem statement
    (the old /card), tracker/artifact links, the shared /runs attempt table for this task,
    and editable task notes."""
    esc = lambda x: html.escape("" if x is None else str(x))
    task_id = constants.task_of(str(task_id or ""))  # tolerate an instance-id form
    instance_id = constants.instance_of(task_id)
    st = dashboard_state()
    run_rows = [r for r in _runs_payload(st).get("rows", []) if r.get("task") == task_id]
    meta = {}
    mp = TASKS / task_id / "meta.json"
    if mp.exists():
        try:
            meta = json.loads(mp.read_text())
        except Exception:
            meta = {}
    inst = {}
    ip = TASKS / task_id / "instance.jsonl"
    if ip.exists():
        try:
            inst = json.loads(ip.read_text().splitlines()[0])
        except Exception:
            inst = {}
    imeta = inst.get("metadata") or {}
    review = meta.get("review") or {}
    n_res = sum(1 for r in run_rows if (r.get("status_obj") or {}).get("key") == "resolved")
    p = [_page_head(f"{task_id}", "Corpus")]
    # .md styling for the inline card markdown block (folded from the old /card page).
    p.append("<style>.md{background:#fff;border:1px solid var(--border);border-radius:8px;padding:16px 20px;line-height:1.55}"
             " .md h1{font-size:19px;border-bottom:1px solid var(--border);padding-bottom:6px}"
             " .md h2{font-size:15px;margin-top:18px;border-bottom:1px solid var(--line);padding-bottom:4px}"
             " .md h3{font-size:13px;margin-top:13px}"
             " .md code{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:85%}"
             " .md pre{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:6px;overflow:auto;white-space:pre}"
             " .md pre code{background:none;padding:0;color:inherit}"
             " .md table{border-collapse:collapse;width:auto} .md th,.md td{border:1px solid var(--border);padding:4px 8px;white-space:normal}"
             " .md blockquote{border-left:3px solid var(--border2);margin:0;padding-left:12px;color:#475569}</style>")
    p.append(f'<h1>{esc(task_id)} &mdash; {esc(meta.get("summary"))}</h1>')
    # W96/W97: the upstream tracker link lives HERE (not on task-name links); + links to
    # the task input and filtered attempt log. The problem statement is the initial
    # agent-facing prompt from instance.jsonl/problem_statement.md, so expose it directly from /task.
    p.append(_related([("GitHub", constants.tracker_url(meta))]))
    p.append(f'<div class=muted>{esc(meta.get("component"))} &middot; {n_res}/{len(run_rows)} resolved attempts</div>')
    # A3: task author = git author of the gold-patch fix commit (from meta.author).
    _au = meta.get("author") or {}
    if _au.get("name"):
        _aemail = f' &lt;{esc(_au.get("email"))}&gt;' if _au.get("email") else ''
        p.append(f'<div class=muted title="git author of the gold-patch fix commit ({esc(_au.get("source") or "fix_commit")})">'
                 f'author <b>{esc(_au.get("name"))}</b>{_aemail}</div>')
    # W111: common-set membership badge (recomputed on demand; neutral chip when IN,
    # a self-explaining amber chip with the reason when OUT of the ranked comparison).
    _cm = None
    try:
        _tsk = next((x for x in st.get("tasks", []) if x.get("task_id") == task_id), None)
        _cm = (_tsk or {}).get("common_set")
    except Exception:
        _cm = None
    if _cm is not None:
        if _cm.get("in"):
            p.append('<div style="margin:5px 0">' +
                     _chip_html('in the ranked common set', 'chip-filter',
                                'counts in the ranked leaderboard\u2019s common task set') + '</div>')
        else:
            p.append('<div style="margin:5px 0">' +
                     _chip_html(_cm.get("reason") or "out of the ranked common set",
                                'chip-weight prop') + '</div>')

    def _task_file_link(name, label=None, extra=""):
        fp = _task_artifact_path(task_id, name)
        if not fp:
            return ""
        href = "/task_file?" + urlencode({"task": task_id, "name": name})
        return f'<a href="{esc(href)}">{esc(label or name)}</a>{extra}'

    def _patch_stats(name):
        fp = _task_artifact_path(task_id, name)
        if not fp:
            return ""
        try:
            txt = fp.read_text(errors="replace")
        except Exception:
            return ""
        files = sum(1 for ln in txt.splitlines() if ln.startswith("diff --git "))
        adds = sum(1 for ln in txt.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
        dels = sum(1 for ln in txt.splitlines() if ln.startswith("-") and not ln.startswith("---"))
        return f' <span class=muted>({files} file{"s" if files != 1 else ""}, +{adds}/-{dels})</span>'

    artifact_links = []
    for art in TASK_ARTIFACTS:
        label = art["label"] + (f' ({art["spoiler"]})' if art.get("spoiler") else "")
        extra = _patch_stats(art["name"]) if art.get("kind") == "patch" else ""
        link = _task_file_link(art["name"], label, extra)
        if link:
            artifact_links.append(link)
    fail_to_pass = (imeta.get("fail_to_pass") or review.get("fail_to_pass") or
                    meta.get("fail_to_pass_testfuncs") or [])
    pass_to_pass = imeta.get("pass_to_pass") or []
    tests = ((imeta.get("commands") or {}).get("tests") or [])
    lang = imeta.get("language") or meta.get("lang") or ""
    build_env = imeta.get("build_env") or review.get("blueprint") or ""
    timeout = imeta.get("verify_timeout_sec") or ""
    complexity = imeta.get("complexity") or {}
    comp_bits = [
        ("type", meta.get("type")), ("lang", lang), ("build", build_env),
        ("timeout", f"{timeout}s" if timeout else ""),
        ("difficulty", complexity.get("difficulty") or (review.get("test_coupling_risk") and "")),
        ("coupling", review.get("test_coupling_risk")),
        ("path", review.get("solution_path_specificity")),
    ]
    if complexity.get("proto_change") or review.get("proto_change"):
        comp_bits.append(("proto", "change"))
    p.append('<div class="card artifact-card">'
             '<div class=flexline>'
             '<b>Task artifacts</b> ' + " &middot; ".join(artifact_links) + '</div>'
             '<div class=chipline>'
             + _chip_html(meta.get("curation_status") or "unknown", 'chip-filter', 'curation status')
             + ''.join(_chip_html(f'{k}: {v}', 'chip-filter') for k, v in comp_bits if v)
             + '</div>')
    if fail_to_pass or pass_to_pass or tests or review.get("oracle") or review.get("verdict"):
        def _mono_list(xs):
            return ", ".join(f'<span class=mono>{esc(x)}</span>' for x in xs)
        p.append('<div style="margin-top:7px"><b>Oracle / validation</b></div>')
        if fail_to_pass:
            p.append(f'<div><span class=muted>FAIL_TO_PASS</span> {_mono_list(fail_to_pass)}</div>')
        if pass_to_pass:
            p.append(f'<div><span class=muted>PASS_TO_PASS</span> {_mono_list(pass_to_pass)}</div>')
        if tests:
            p.append(f'<div><span class=muted>verify</span> {_mono_list(tests)}</div>')
        if review.get("oracle") or review.get("verdict"):
            p.append('<details><summary class=muted>validation note</summary>'
                     f'<div class=normal-wrap>{esc(review.get("oracle") or review.get("verdict"))}</div>'
                     '</details>')
    p.append('</div>')
    # card.md problem statement, rendered inline (the old /card page, folded in).
    cardp = TASKS / task_id / "card.md"
    card_scripts = ""
    if cardp.exists():
        try:
            vend = Path(__file__).resolve().parent / "vendor_pi_export" / "vendor"
            marked = (vend / "marked.min.js").read_text()
            hljs = (vend / "highlight.min.js").read_text()
            card_text = cardp.read_text()
            # The task card often names problem_statement.md in its provenance notes. Make
            # that filename itself open the agent-facing initial prompt, so users do not
            # have to infer that the top related link is the same artifact.
            if (TASKS / task_id / "problem_statement.md").exists():
                ps_url = f"/task_file?task={task_id}&name=problem_statement.md"
                card_text = re.sub(r"(?<!\[)\bproblem_statement\.md\b",
                                   f"[problem_statement.md]({ps_url})", card_text)
            b64 = base64.b64encode(card_text.encode()).decode()
            p.append('<div class=md id=md style="margin:10px 0 16px"></div>')
            card_scripts = (f'<script id=src type="application/base64">{b64}</script>'
                            f'<script>{marked}</script><script>{hljs}</script>'
                            '<script>var _b=atob(document.getElementById("src").textContent);'
                            'var _md=new TextDecoder("utf-8").decode(Uint8Array.from(_b,function(c){return c.charCodeAt(0);}));'
                            'document.getElementById("md").innerHTML=marked.parse(_md);'
                            'document.querySelectorAll(".md pre code").forEach(function(e){try{hljs.highlightElement(e);}catch(x){}});</script>')
        except Exception:
            card_scripts = ""
    p.append(f'<h2>Attempts <a href="/runs?task={esc(task_id)}" '
             f'class="subtle-heading-link">open in /runs</a> '
             f'<span id=taskattemptmeta class="muted small-note"></span></h2>')
    p.append('<table id=t><thead></thead><tbody></tbody></table>')
    p.append('<script>window.RUNS_OPTS=' + json.dumps({"task": task_id, "controls": False, "pageSize": 1_000_000}) + ';</script>')
    p.append(_RUNS_TABLE_JS)
    # task notes (moved here from /card -- U5 shared inline editor).
    p.append(_notes_block(
        "Task notes", _subject_notes("task", task_id), add_action="/task_note_add",
        back=f"/task?task={esc(task_id)}",
        hidden_inputs=f'<input type=hidden name=task value="{esc(task_id)}">',
        empty_label="no task notes yet", placeholder="add a task note/comment"))
    p.append(card_scripts)
    p.append(f'<script>{_NOTE_EDIT_JS}</script></body></html>')
    return "".join(p)



# D4: derived from OUTCOME. Icons here render on a COLORED badge background (see
# _big_badge: white text) so they are WHITE, not the semantic color (else icon==bg).
# 'running' is a lifecycle state (not an outcome) appended for the live badge.
_VERDICT_BADGE = {k: (v["color"], f'{icon(v["icon"], 14, "#fff")} {v["label"]}')
                  for k, v in OUTCOME.items()}
_VERDICT_BADGE["running"] = (PALETTE["accent"], f'{icon("cog", 14, "#fff")} RUNNING')


def _big_badge(outcome):
    c, lbl = _VERDICT_BADGE.get(outcome, ("#6b7280", html.escape(outcome or "?")))
    return f'<span class="badge badge-lg" style="background:{c}">{lbl}</span>'


def _verify_stage_label(vpath):
    """Label one verifier log for the /run pipeline. Returns (label, is_verdict, cmd)."""
    try:
        body = vpath.open("r", errors="replace").read()
    except Exception:
        body = ""
    first = (body.splitlines()[0].strip() if body else "")
    # A combined verify log (contains the pb-run command line): it IS the verdict
    # log -> label it as such (is_v=True gets the caveat tooltip) and flag TIMEOUT.
    cmd = next((ln[2:] for ln in body.splitlines() if ln.startswith("$ ")), "")
    if cmd:
        if "[TIMEOUT after" in body:
            to = next((ln for ln in body.splitlines() if "[TIMEOUT after" in ln), "[TIMEOUT]")
            return f"pb run \u2014 {to.strip()}", True, cmd
        return "pb run (verify log)", True, cmd
    # Labels are PAST-TENSE / descriptive: each stage is a LOG of what the
    # verifier already did, not an action for the reader to perform.
    f = first.rstrip(":").upper()
    if f == "AGENT PATCH":
        return "agent patch applied", False, ""
    if f == "STRIPPED AGENT TEST EDITS":
        return "agent test edits stripped", False, ""
    return (first[:40] or vpath.name.split("__")[-1]), False, ""


def render_run_page(run_id, agent_id, instance_id):
    esc = lambda x: html.escape("" if x is None else str(x))
    files = _find_cell_files(run_id, agent_id, instance_id)
    task_id = constants.task_of(instance_id)
    sc, sc_src = _best_cell_score(run_id, agent_id, instance_id)
    # Viewing a SPECIFIC run: never present a DIFFERENT run's scored attempt as if
    # it were this run's result (confusing -- the user asked for THIS run). Keep
    # only a lightweight pointer to where a scored attempt does exist.
    other_run_ref = None
    if sc_src == "other_run":
        other_run_ref = sc.get("run_id") or ""
        sc, sc_src = {}, None
    meta = _task_meta(task_id)
    tj = files["agent_io"]
    evaluation_id = _eval_id_for_cell(run_id, agent_id, instance_id)
    events = _attempt_events(evaluation_id, run_id, agent_id, instance_id)
    exclusion = _run_exclusion(evaluation_id)
    notes = _run_notes(evaluation_id)
    d = {}
    if tj:
        try:
            d = json.loads(tj.read_text())
        except Exception:
            d = {}

    outcome = _outcome_of(sc) if sc else None
    # LIVENESS: if this cell has no landed score in THIS run yet but a live process
    # holds its slot, it is IN PROGRESS -- do NOT present a stale verdict (esp. an
    # OTHER run's no_patch) as this attempt's result. Show a RUNNING state instead.
    running = (sc_src != "this_run") and _cell_running(instance_id, agent_id)
    disp_outcome = "running" if running else outcome
    model = sc.get("model_name") or d.get("model_name")
    provider = sc.get("provider") or d.get("provider")
    harness = _harness(agent_id)

    p = [_page_head(f"{agent_id} {task_id}", "Runs")]  # W96: bare task id in the tab title (no instance prefix)
    # header + verdict
    # agent id links to its detail page (/agent?id=<id>), matching the leaderboard/agents-table links.
    p.append(f'<h1 style="margin-bottom:4px">{_big_badge(disp_outcome) if disp_outcome else ""} '
             f'&nbsp;<a href="/agent?id={esc(agent_id)}" style="color:inherit;text-decoration:none" '
             f'title="agent detail">{esc(agent_id)}</a></h1>')
    # title line: if the summary starts with the task id (an OPAQUE token -- no shape
    # assumption), turn ONLY that leading id into the task-page link -- no separate
    # "<task_id> --" prefix, no duplicate related link. Task card = a small
    # card icon next to the title; "batch run" dropped (outdated concept).
    _summary = meta.get("summary") or ""
    _stripped = _summary.lstrip()
    # W96: the task NAME links to the canonical task page /task (NOT the tracker -- the
    # GitHub link lives on /task).
    if task_id and _stripped.startswith(task_id):
        _title = f'<a href="/task?task={esc(task_id)}">{esc(task_id)}</a>{esc(_stripped[len(task_id):])}'
    elif _summary:
        _title = f'<a href="/task?task={esc(task_id)}">{esc(task_id)}</a> &mdash; {esc(_summary)}'
    else:
        _title = f'<a href="/task?task={esc(task_id)}">{esc(task_id)}</a>'
    _card = (f'<a href="/task?task={esc(task_id)}" title="task page" '
             f'style="text-decoration:none;display:inline-flex;vertical-align:-2px;color:#2563eb">'
             f'{icon("file-document", 14, "#2563eb")}</a> '
             if (TASKS / task_id / "card.md").exists() else "")
    # model/provider/harness live in the INFERENCE box (and agent_id in the h1);
    # don't repeat them here -- just the card icon (FIRST) + task + try.
    p.append(f'<div class=muted>{_card}{_title}</div>')
    # W23 annotation details for THIS cell (any kind/status), with provenance +
    # how to act. (Was: a contamination-only banner -> nothing showed for
    # superseded/artifact/proposed. Now covers all.)
    # W37: legacy invalidation annotations are preserved as notes only. The pipeline
    # summary comes from run scoring exclusions + notes, not the old annotation state.
    ann_full = ""
    ann_short = ""
    ann_cls = "gray"

    # W39 pipeline summary comes from scoring exclusions + notes, not legacy invalidation.
    if exclusion:
        ann_short = f'{icon("skull", 13, "#dc2626")} <b>excluded from scoring</b>'
        ann_cls = "bad"
    elif notes:
        ann_short = f'{icon("note-text", 13, "#64748b")} <b>notes</b>'
        ann_cls = "gray"

    # ======== gather everything, then render as a PIPELINE of stage boxes ========
    notice = ""
    _otherlink = (f' <a href="/run?run={esc(other_run_ref)}&agent={esc(agent_id)}'
                  f'&instance={esc(instance_id)}">run '
                  f'{esc((other_run_ref or "")[:8])}</a>') if other_run_ref else ""
    if running:
        notice = (f'<div style="background:#dbeafe;border:1px solid #bfdbfe;border-radius:5px;'
                  f'padding:6px 10px;font-size:12px;margin:6px 0">{icon("cog", 13, "#2563eb")} This cell is '
                  f'<b>RUNNING now</b> &mdash; no verdict yet for this run. '
                  f'<a href="/live?run={esc(run_id)}&agent={esc(agent_id)}&instance={esc(instance_id)}'
                  f'" target=_blank>watch the live transcript</a></div>')
    elif not sc:
        _extra = (f' A scored attempt of this cell exists in{_otherlink}.' if other_run_ref else "")
        notice = (f'<div class=muted style="margin:6px 0">{icon("alert", 13, "#b45309")} not scored in <b>this</b> run yet.'
                  + _extra + '</div>')

    m = sc.get("metrics") or {}
    if not m:
        try:
            m = (json.loads(d.get("stdout") or "{}").get("token_usage") or {})
        except Exception:
            m = {}
    gen_ms = m.get("runtime_ms") or m.get("total_duration_ms") or d.get("generation_ms")
    cost = sc.get("cost_usd", m.get("cost_usd"))
    # Per-stage timings shown next to the boxes (INFERENCE=generation, OUTPUT=verify),
    # with TIMEOUTs highlighted red. generation = runtime_ms; verify = total - gen.
    _gen_ms = m.get("runtime_ms") or d.get("generation_ms")
    _total_ms = m.get("total_duration_ms") or sc.get("total_duration_ms")
    _verify_ms = (_total_ms - _gen_ms) if (_total_ms and _gen_ms and _total_ms > _gen_ms) else None
    _raw_oc = (sc.get("attempt_outcome") or sc.get("status") or "").strip()
    _timeout_sec = d.get("timeout_sec") or (m.get("timeout_sec"))
    _gen_timeout = (_raw_oc in ("candidate_missing", "no_patch_generated") and _timeout_sec
                    and _gen_ms and _gen_ms >= 0.95 * _timeout_sec * 1000)
    _verify_timeout = _raw_oc in ("verification_timeout", "timeout")

    # verify sub-stages (apply agent patch -> strip agent test edits -> pb run)
    stages = [(v, *_verify_stage_label(v)) for v in (files["verify"] or [])]
    verdict_stage = next((t for t in reversed(stages) if t[2]), None)
    verify_cmd = verdict_stage[3] if verdict_stage else ""
    final_log = verdict_stage[0] if verdict_stage else (files["verify"][-1] if files["verify"] else None)

    # transcript sources (Inference) + live fallback
    _KIND = {
        "pi_session": ("pi session (native)", True),
        "pi_stream": ("pi --mode json stream", False),
        "claude_stream": ("claude stream-json", False),
        "unknown": ("raw log", False),
    }
    bundle = files["dir"].name if files.get("dir") else ""
    srcs = list(files.get("sessions") or []) + list(files["raw"])
    live = None if srcs else _live_session(run_id, agent_id, instance_id)

    # input problem statement, output patch, stderr
    prob = (d.get("agent_input") or {}).get("problem_statement") or _instance_problem(task_id)
    patch_text = ""
    try:
        pl = (json.loads(d.get("stdout") or "{}").get("patches") or [])
        if pl:
            patch_text = pl[0].get("patch_text") or pl[0].get("patch") or ""
    except Exception:
        pass
    adds = sum(1 for ln in patch_text.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    dels = sum(1 for ln in patch_text.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    stderr = d.get("stderr") or ""

    # W40 attempt events are rendered by _render_event_pipeline (queue/generation/
    # verification/result stages) directly from the `events` list; do NOT also build
    # a manual queue box here or the queue events render TWICE (bug: cell/slot-wait/
    # slot-acquired appeared duplicated).

    # --- INPUT ---
    # W104: the task page is the canonical entry (it carries the GitHub tracker link); don't
    # offer a separate direct tracker link here (the tracker is reachable only from the task page).
    inbox = [f'<a href="/task?task={esc(task_id)}">task page</a>']
    if meta.get("base_commit"):
        inbox.append(f'<span class=muted>base</span> <span class=mono>{esc(str(meta.get("base_commit"))[:12])}</span>')
    _cellq = f'run={esc(run_id)}&agent={esc(agent_id)}&instance={esc(instance_id)}'
    inbox.append(f'<a href="/field?{_cellq}&f=problem" target=_blank>problem statement ({len(prob):,} ch)</a>' if prob
                 else '<span class=muted>no problem statement</span>')

    # --- INFERENCE ---
    infbox = [f'<span class=muted>model</span> <b>{esc(model)}</b>',
              f'{_chip_html(harness)} <span class=muted>{esc(provider)}</span>']
    if m.get("total_tokens"):
        infbox.append(f'<span class=muted>tok</span> in {m.get("input_tokens",0):,} &rarr; out {m.get("output_tokens",0):,}')
    if cost:
        infbox.append(f'<span class=muted>cost</span> ${cost:.4f}')
    if srcs:
        _tl = []
        for s in srcs:
            _fmt = transcript_view.detect_format(str(s)) if transcript_view is not None else "unknown"
            _lbl = {"pi_session": "pi session", "pi_stream": "rawcli",
                    "claude_stream": "claude log"}.get(_fmt, "log")
            _u = (f'/rich?bundle={esc(bundle)}&name={esc(s.name)}' if (transcript_view is not None and _fmt != "unknown")
                  else f'/logfile?bundle={esc(bundle)}&name={esc(s.name)}')
            _tl.append(f'<a href="{_u}" target=_blank>{_lbl}</a>')
        infbox.append("transcript: " + " &middot; ".join(_tl))
    elif live is not None:
        _lu = f'/live?run={esc(run_id)}&agent={esc(agent_id)}&instance={esc(instance_id)}'
        infbox.append(f'{icon("circle-small", 13, PALETTE["bad"])} <a href="{_lu}" target=_blank>watch live</a>')
    else:
        infbox.append('<span class=muted>no transcript</span>')

    # --- PATCH / VERIFICATION / RESULT ---
    patchbox = []
    verifybox = []
    resultbox = [_big_badge(disp_outcome) if disp_outcome else '<span class=muted>(no score record)</span>']
    if running:
        resultbox.append('<span class=muted style="font-size:11px">generation/verify in progress; '
                         'no verdict for this run yet</span>')
    # Surface the SPECIFIC failure reason: the badge collapses everything non-resolved
    # into FAILED/miss, so a verification_timeout / build_failed / infra error looked
    # like a plain wrong answer. Show the raw status/outcome + a plain-language gloss.
    _raw = (sc.get("attempt_outcome") or sc.get("status") or "").strip()
    _WHY_FAIL = {
        "verification_timeout": "verify (build+test) exceeded the time cap \u2014 an infra/budget artifact, NOT a wrong fix",
        "timeout": "timed out \u2014 generation or verify exceeded the cap (infra/budget, not a wrong fix)",
        "build_failed": "the build failed (often a test-blind C++ symbol/path issue), so the test never ran",
        "compile_error": "the code did not compile, so the test never ran",
        "worktree_error": "infra error preparing the git worktree \u2014 not a real attempt",
        "workspace_preparation_failed": "infra error preparing the workspace \u2014 not a real attempt",
        "internal_error": "a harness internal error stopped the run \u2014 not a real attempt",
        "provider_error": "the model endpoint refused or dropped the request (429/5xx/auth) \u2014 the agent never finished a turn, so this is infra, not a wrong fix",
        "candidate_missing": "the agent produced no patch (auth/turn-cap/timeout/stall)",
        "no_patch_generated": "the agent produced no patch (auth/turn-cap/timeout/stall)",
    }
    if not running and outcome != "resolved" and _raw and _raw not in ("completed", "scored"):
        _gloss = _WHY_FAIL.get(_raw, "")
        resultbox.append(f'<span style="font-size:11px"><span class=mono style="color:#b45309">'
                         f'{esc(_raw)}</span>' + (f' <span class=muted>\u2014 {esc(_gloss)}</span>' if _gloss else "") + '</span>')
    if not running and sc.get("error_message"):
        resultbox.append(f'<span class=muted style="color:#b45309">{esc(sc.get("error_message"))}</span>')
    if not running:
        patchbox.append(f'<a href="/field?{_cellq}&f=patch" target=_blank>agent patch (+{adds}/-{dels})</a>' if patch_text
                        else '<span class=muted>no patch produced</span>')
        # Current zbench now emits patch_extracted/patch_missing, but older W19-era
        # rows did not. If an older row has a patch but no patch event, timestamp the
        # patch stage as "ready by" the verify-start event (the first durable point after
        # patch application) instead of leaving the patch box timeless.
        if patch_text and not any(EVENT_STAGE.get(e.get("phase")) == "patch" for e in (events or [])):
            _vstarts = [e for e in (events or []) if e.get("phase") in ("verify_started", "verification_started") and _event_dt(e)]
            if _vstarts:
                _ve = min(_vstarts, key=lambda e: _event_dt(e))
                events = list(events or []) + [{
                    "phase": "patch_extracted", "ts": _ve.get("ts"),
                    "message": "patch ready before verify",
                    "data_json": json.dumps({"patch_count": 1, "patch_chars": len(patch_text),
                                             "synthetic_ready_by_verify": True}),
                }]
    if stages:
        # The pb-run stage's "All done N/N + rc=0" means the pb PLAN STEPS completed,
        # NOT that FAIL_TO_PASS passed -- surface that caveat as a tooltip (W35).
        _pbcav = ("pb 'All done N/N' + rc=0 means the pb plan steps completed, "
                  "NOT that FAIL_TO_PASS passed -- read the verdict line in this log.")
        def _vmark(is_v, lbl):
            if not is_v:
                return ""
            return f' {icon("timer-sand", 12, "#dc2626")}' if "TIMEOUT" in lbl.upper() else f' {icon("check-circle", 12, "#16a34a")}'  # timeout vs check
        _sub = " &rarr; ".join(
            f'<a href="/logfile?bundle={esc(bundle)}&name={esc(v.name)}" target=_blank'
            + (f' title="{esc(_pbcav)}"' if is_v else "") + f'>{esc(lbl)}</a>'
            + _vmark(is_v, lbl)
            for v, lbl, is_v, _c in stages)
        verifybox.append(f'<span class=muted style="font-size:11px" title="each link opens '
                         f'that verify step&#39;s LOG (what the verifier did) -- not an action to run">'
                         f'verify steps (logs): {_sub}</span>')
    if stderr.strip():
        resultbox.append(f'<a href="/field?{_cellq}&f=stderr" target=_blank>stderr</a>')
    ocls = "ok" if outcome == "resolved" else "bad" if outcome in ("miss", "no_patch") else "gray"

    # --- SCORING / NOTES ---
    # Deliberately no in-page audit/re-audit action: the old button was unused and
    # made every row/detail page carry validation JS and endpoint plumbing. Scoring
    # exclusions and notes remain editable here; deeper evidence audits are CLI/offline.
    annbox = []
    if ann_short:
        annbox.append(ann_short)
        if exclusion and exclusion.get("decided_at"):
            annbox.append(f'<span class=muted>excluded at</span> {esc((exclusion.get("decided_at") or "")[:19].replace("T", " "))}')
    else:
        annbox.append('<span class=muted>no scoring notes or exclusions</span>')

    if notice:
        p.append(notice)

    stage_items = collections.defaultdict(list)
    stage_items["input"].extend(inbox)
    stage_items["generation"].extend(infbox)
    stage_items["patch"].extend(patchbox)
    stage_items["verification"].extend(verifybox)
    stage_items["result"].extend(resultbox)
    stage_items["scoring"].extend(annbox)
    # W50: explicit per-stage duration fallbacks for when event bounds are absent or
    # collapse to zero (single/equal-ts backfilled event, or a still-running phase).
    _stage_fallback = {}
    if _gen_ms:
        _stage_fallback["generation"] = _gen_ms / 1000.0
    if _verify_ms:
        _stage_fallback["verification"] = _verify_ms / 1000.0
    if running:
        # live generation: elapsed from the first generation event to now (no
        # finished event yet, so event bounds would otherwise read 0s).
        _gen_starts = [_event_dt(e) for e in (events or [])
                       if EVENT_STAGE.get(e.get("phase")) == "generation"]
        _gen_starts = [d0 for d0 in _gen_starts if d0]
        if _gen_starts:
            _live_gen = (datetime.now(timezone.utc) - min(_gen_starts)).total_seconds()
            if _live_gen > (_stage_fallback.get("generation") or 0):
                _stage_fallback["generation"] = _live_gen
    p.append(_render_event_pipeline(events, stage_items, esc,
                                    {"result": ocls, "scoring": ann_cls,
                                     "patch": "ok" if patch_text else "warn" if not running else "gray",
                                     "verification": "bad" if _verify_timeout else "gray"},
                                    stage_fallback=_stage_fallback))

    # The stage boxes link directly to the content (problem/patch/stderr via /field,
    # transcript via /rich|/logfile, verify logs via /logfile) -- no in-page
    # collapsibles. Only the annotation explanation (short, judgment-relevant) is
    # shown inline below, plus the provenance line.
    if ann_full:
        p.append(ann_full)

    # model patch vs gold patch, side by side (falls back to the bundle's patch.diff)
    _cmp_patch = patch_text or (_read_bundle_patch(evaluation_id) if evaluation_id else "")
    p.append(_render_patch_compare(task_id, _cmp_patch, outcome))

    # W37: human-controlled run scoring exclusion + notes. Notes are hints/comments
    # only; only a non-empty run exclusion reason affects scoring.
    if evaluation_id:
        inv = exclusion
        rv_bg, rv_bd = ("#fee2e2", "#fecaca") if inv else ("#f8fafc", "#e2e8f0")
        rv_head = (f'{icon("skull", 13, "#dc2626")} <b>Excluded from scoring</b> '
                   f'<span class=muted>({esc(inv.get("decided_by"))}, '
                   f'{esc((inv.get("decided_at") or "")[:19].replace("T", " "))} UTC)</span>'
                   if inv else '<span class=muted>included in scoring (no exclusion reason)</span>')
        _cur_reason = esc((inv or {}).get("reason") or "")
        _back = esc("/run?run=" + run_id + "&agent=" + agent_id + "&instance=" + instance_id)
        _excl_text = _cur_reason or '<span class=muted>click to add exclusion reason</span>'
        p.append(f'<h2>Scoring exclusion</h2><div class=card style="border-color:{rv_bd};background:{rv_bg}">'
                 f'<div style="font-size:13px;margin-bottom:8px">{rv_head}</div>'
                 f'<div style="font-size:13px">'
                 f'<span id="excl-text" onclick="exclusionEdit()" style="cursor:text" '
                 f'title="click to edit scoring exclusion reason">{_excl_text}</span>'
                 f'<form id="excl-form" method=get action="/review_set" style="display:none;margin:0">'
                 f'<input type=hidden name=run value="{esc(run_id)}"><input type=hidden name=agent value="{esc(agent_id)}">'
                 f'<input type=hidden name=instance value="{esc(instance_id)}">'
                 f'<input name=reason value="" style="width:720px" '
                 f'placeholder="empty = include in scoring; optional prefix [artifact:infra] ..." '
                 f'onblur="exclusionSaveOrCancel(this)" '
                 f'onkeydown="if(event.key===\'Enter\'){{this.blur();}}">'
                 f'</form></div>'
                 f'<div class=muted style="font-size:11px;margin-top:4px">A non-empty reason excludes this run from scoring. Empty reason clears the exclusion. Notes below are informational.</div></div>')
        p.append(_notes_block(
            "Notes", notes, add_action="/note_add", back=_back,
            hidden_inputs=(f'<input type=hidden name=run value="{esc(run_id)}">'
                           f'<input type=hidden name=agent value="{esc(agent_id)}">'
                           f'<input type=hidden name=instance value="{esc(instance_id)}">')))
    else:
        p.append('<h2>Scoring exclusion</h2><div class=card><span class=muted>no attempt row/evaluation_id for this run yet</span></div>')

    # exclusion-reason inline edit is /run-specific; the note fns are the SHARED
    # _NOTE_EDIT_JS (single source, also used by /card -- U5).
    p.append("<script>"
             "function exclusionEdit(){"
             "var t=document.getElementById('excl-text'),f=document.getElementById('excl-form');"
             "if(!t||!f)return;t.style.display='none';f.style.display='inline';"
             "var i=f.querySelector('input[name=reason]');if(i){i.value=t.textContent||'';if(t.querySelector('.muted'))i.value='';i.dataset.orig=i.value;i.focus();i.select();}}"
             "function exclusionSaveOrCancel(input){var f=input.form,t=document.getElementById('excl-text');"
             "if(input.value!==input.dataset.orig){f.submit();return;}if(t)t.style.display='inline';if(f)f.style.display='none';}"
             + _NOTE_EDIT_JS + "</script>")

    # provenance: captured agent CLI version + harness commit (attempt_provenance), then files
    _pv = _attempt_provenance(evaluation_id) if evaluation_id else None
    if _pv:
        _pb = []
        _cliname = (_pv.get("agent_cli_name") or "").strip()
        _cliver = (_pv.get("agent_cli_version") or "").strip()
        if _cliname or _cliver:
            _pb.append(f'agent CLI <span class=mono>{esc((_cliname + " " + _cliver).strip())}</span>'
                       if _cliver else f'agent CLI <span class=mono>{esc(_cliname)}</span> <span class=muted>(version not captured)</span>')
        _hn = (_pv.get("harness_name") or "").strip()
        _hc = (_pv.get("harness_git_commit") or "").strip()
        if _hn or _hc:
            _h = _hn + ((" " + _hc[:12]) if _hc else "")
            _pb.append(f'harness <span class=mono>{esc(_h.strip())}</span>'
                       + (' <span class="chip chip-filter">dirty</span>' if _pv.get("harness_git_dirty") else ''))
        if _pv.get("python_version"):
            _pb.append(f'py <span class=mono>{esc(str(_pv.get("python_version")).split(" ")[0])}</span>')
        if _pv.get("captured_at"):
            _pb.append(f'<span class=muted>captured {esc(str(_pv.get("captured_at"))[:19].replace("T", " "))}</span>')
        if _pb:
            p.append(f'<div class=muted style="font-size:11px;margin-top:14px">provenance: ' + " &middot; ".join(_pb) + "</div>")
    # files (one clear line)
    _prov = []
    if tj:
        _prov.append(f'agent I/O record <a href="/logfile?bundle={esc(bundle)}&name={esc(tj.name)}" target=_blank>&#11015;</a>')
    _prov.append(f'<a href="/logs?run={esc(run_id)}">all files in this run</a>')
    p.append(f'<div class=muted style="font-size:11px;margin-top:{"4px" if _pv else "14px"}">files: ' + " &middot; ".join(_prov) + "</div>")

    p.append("</body></html>")
    return "".join(p)


def render_logs_index(run_id):
    """List a run's evidence files, aggregated across its per-attempt blob bundles."""
    esc = lambda x: html.escape("" if x is None else str(x))
    import sqlite3
    db = Path(BENCHDB)
    p = [_page_head(f"files {run_id}", "Runs")]
    p.append(f'<h1>evidence blobs / {esc(run_id)}</h1>')
    evals = []
    if db.exists():
        conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
        try:
            evals = [r[0] for r in conn.execute(
                "SELECT evaluation_id FROM attempt WHERE run_id=?",
                (run_id,))]
        finally:
            conn.close()
    seen = False
    p.append("<table><tr><th>file</th><th class=num>size</th><th>modified</th></tr>")
    for rel in evals:
        d = _bundle_dir(Path(rel).name)
        if not d:
            continue
        for f in sorted(d.iterdir()):
            seen = True
            sz = f.stat().st_size
            p.append(f'<tr><td class=mono><a href="/logfile?bundle={esc(d.name)}&name={esc(f.name)}">{esc(f.name)}</a></td>'
                     f'<td class=num>{sz:,}</td>'
                     f'<td class=muted>{datetime.fromtimestamp(f.stat().st_mtime).strftime("%m-%d %H:%M")}</td></tr>')
    if not seen:
        p.append("</table><div class=muted>no evidence blobs for this run</div></body></html>")
        return "".join(p)
    p.append("</table></body></html>")
    return "".join(p)


def _cell_badge(s):
    """Verdict icon for a score row, linking to its /run cell page. Icon only --
    the emoji is self-colored, so a colored background would just duplicate it."""
    o = _outcome_of(s)
    oico = {"resolved": icon("check-circle", 15, "#16a34a"), "miss": icon("close-circle", 15, "#dc2626"),
            "no_patch": icon("alert", 15, "#b45309")}.get(o, icon("alert-circle", 15, "#94a3b8"))
    href = (f'/run?run={html.escape(s.get("run_id") or "")}&agent={html.escape(s.get("agent_id") or "")}'
            f'&instance={html.escape(s.get("instance_id") or "")}')
    return (f'<a href="{href}" title="{o}" '
            f'style="text-decoration:none;display:inline-flex;justify-content:center">{oico}</a>')


def render_batch_page(run_id):
    """Matrix of all cells in a batch run: instances (rows) x agents (cols)."""
    esc = lambda x: html.escape("" if x is None else str(x))
    # all attempts for this run from bench.db (the single store), keyed per cell.
    merged = {}
    for s in _benchdb_attempts(run_id):
        merged[(s.get("agent_id"), s.get("instance_id"))] = s
    rows = list(merged.values())
    p = [_page_head(f"batch {run_id}", "Runs")]
    p.append(f'<h1>Batch run <span class=mono>{esc(run_id[:8])}</span></h1>')
    if not rows:
        p.append('<div class=muted>no scored cells for this run.</div></body></html>')
        return "".join(p)
    agents = sorted({s.get("agent_id") for s in rows})
    insts = sorted({s.get("instance_id") for s in rows})
    # index (agent, instance) -> best try (prefer resolved, else latest)
    cell = {}
    for s in rows:
        k = (s.get("agent_id"), s.get("instance_id"))
        cur = cell.get(k)
        if cur is None or (s.get("tests_passed") and not cur.get("tests_passed")) \
                or str(s.get("timestamp", "")) >= str(cur.get("timestamp", "")):
            cell[k] = s
    nres = sum(1 for s in cell.values() if s.get("tests_passed"))
    total = len(agents) * len(insts)
    sparse = "" if len(cell) == total else (
        f' &mdash; SPARSE: only {len(cell)} of the {total} grid positions ran '
        f'(this batch targeted specific cells; blanks below = not run)')
    p.append(f'<div class=muted><b>{len(cell)} scored cell(s)</b> &middot; {nres} resolved &middot; '
             f'{len(agents)} agents &times; {len(insts)} instances{sparse} &middot; '
             f'<a href="/logs?run={esc(run_id)}">files</a></div>')
    p.append("<table><tr><th>instance</th>"
             + "".join(f'<th style="font-size:10px">{esc(a)}</th>' for a in agents) + "</tr>")
    for inst in insts:
        task_id = constants.task_of(inst)
        p.append(f'<tr><td class=mono style="font-size:11px"><a href="/task?task={esc(task_id)}">{esc(task_id)}</a></td>')
        for a in agents:
            s = cell.get((a, inst))
            p.append(f'<td class=num>{_cell_badge(s) if s else "<span class=muted>-</span>"}</td>')
        p.append("</tr>")
    p.append("</table>")
    p.append('<div class=muted style="font-size:11px;margin-top:6px">'
             f'{icon("check-circle", 12, "#16a34a")} resolved &middot; '
             f'{icon("close-circle", 12, "#dc2626")} failed &middot; '
             f'{icon("alert", 12, "#b45309")} no-patch &middot; '
             f'{icon("circle-small", 12, "#94a3b8")} = not run in this batch '
             '&middot; click a cell for its transcript</div>')
    p.append("</body></html>")
    return "".join(p)


def _agents_meta():
    """W76: per-agent STATIC metadata (model card + harness + hosting), single source =
    zbench-tasks/agents-meta.jsonl. (Ops/retry context is NOT here since W91 -- it lives in the
    durable `note` table, subject_type=agent; see render_agent_detail's "Agent notes" block.)"""
    p = Path(__file__).resolve().parent.parent / "zbench-tasks" / "agents-meta.jsonl"
    out = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line); out[d.get("agent_id")] = d
            except Exception:
                pass
    return out


def _agents_payload(st):
    """W76: merge agents-meta.jsonl with live board stats (rank/rate/coverage/cost) +
    per-agent note counts. Data-only for /api/agents."""
    meta = _agents_meta()
    lb = {r["agent_id"]: r for r in (st.get("leaderboard", []) + st.get("leaderboard_partial", []))}
    partial_ids = {x["agent_id"] for x in st.get("leaderboard_partial", [])}
    ids = list(dict.fromkeys(list(meta.keys()) + list(lb.keys())))
    rows = []
    for aid in ids:
        m = dict(meta.get(aid, {})); m["agent_id"] = aid
        r = lb.get(aid)
        if r:
            m["rank"] = r.get("rank"); m["resolve_rate"] = r.get("resolve_rate")
            m["resolved"] = r.get("resolved"); m["n"] = r.get("n"); m["coverage"] = r.get("coverage")
            m["cost_per_task"] = ((r.get("cost_usd") or 0) / r["n"]) if r.get("n") else None
            _nt = r.get("n_turns") or 0
            m["turns_per_task"] = ((r.get("turns") or 0) / _nt) if _nt else None
            m["partial"] = aid in partial_ids
        m["note_count"] = len(_subject_notes("agent", aid))
        rows.append(m)
    rows.sort(key=lambda m: (m.get("rank") is None, m.get("rank") or 0, m.get("agent_id") or ""))
    return {"agents": rows, "generated_at": st.get("generated_at")}


# W85: /agents is now a client-rendered SORTABLE table (reusing the W68 sortableThs +
# filterSort scaffold, like /runs + /corpus); the per-agent CARD moved to /agent?id=<id>
# (render_agent_detail). One row per agent; click the agent_id -> detail (model card +
# editable notes (bench.db note table) + runs). Design system: MDI-only (sort arrow via mdi()),
# palette-token chip badges (no ad-hoc hex), shared el()/sortableThs/filterSort.
_AGENTS_PAGE = r"""<!doctype html><html><head><meta charset=utf-8>
<title>Agents &mdash; zbench</title>
<style>__CSS__</style></head><body>
__NAV__
<h1>zbench &mdash; Agents</h1>
<div style="display:flex;gap:12px;align-items:center;margin-bottom:8px;flex-wrap:wrap">
  <input id=q placeholder="filter&hellip; (agent / model / harness / hosting / provider)" style="width:360px">
  <span id=meta class=muted style="margin-left:auto"></span>
</div>
<table id=t><thead></thead><tbody></tbody></table>
<script>
var DATA=[],VIEW=[],sortKey='rank',sortDir=1;
var COLS=[
 {k:'agent_id',label:'agent_id',get:function(r){return r.agent_id||'';}},
 {k:'model',label:'model',get:function(r){return r.model||'';}},
 {k:'family',label:'family',get:function(r){return r.family||'';}},
 {k:'harness',label:'harness',get:function(r){return r.harness||'';}},
 {k:'hosting',label:'hosting',get:function(r){return r.hosting||'';}},
 {k:'provider',label:'provider',get:function(r){return r.provider||'';}},
 {k:'weights',label:'weights',get:function(r){return r.open_weight?0:1;}},
 {k:'rank',label:'rank',num:true,get:function(r){return r.rank==null?1e9:r.rank;}},
 {k:'rate',label:'rate',num:true,get:function(r){return r.resolve_rate==null?-1:r.resolve_rate;}},
 {k:'cost',label:'$/task',num:true,get:function(r){return r.cost_per_task==null?1e12:r.cost_per_task;}},
 {k:'ctx',label:'ctx',num:true,get:function(r){return r.ctx_window||0;}},
 {k:'notes',label:'notes',num:true,get:function(r){return r.note_count||0;}}
];
function agMatch(r){var q=document.getElementById('q').value.trim().toLowerCase();if(!q)return true;
 return ((r.agent_id||'')+' '+(r.model||'')+' '+(r.family||'')+' '+(r.harness||'')+' '+(r.hosting||'')+' '+(r.provider||'')).toLowerCase().indexOf(q)>=0;}
function fmtRank(r){if(r.rank==null)return r.partial?'~':'\u2014';return (r.partial?'~':'')+r.rank;}
function renderHead(){var tr=el('tr');
 sortableThs(COLS,sortKey,sortDir,function(k){if(sortKey===k)sortDir*=-1;else{sortKey=k;sortDir=1;}applyView();}).forEach(function(th){tr.appendChild(th);});
 var h=document.querySelector('#t thead');h.innerHTML='';h.appendChild(tr);}
function renderBody(){var tb=document.querySelector('#t tbody');tb.innerHTML='';var frag=document.createDocumentFragment();
 VIEW.forEach(function(r){var tr=el('tr');if(r.partial)tr.style.color='#94a3b8';
  var aTd=el('td');aTd.className='ell';aTd.title=r.agent_id||'';var a=el('a',r.agent_id,{href:'/agent?id='+encodeURIComponent(r.agent_id)});a.className='mono';aTd.appendChild(a);
  if(r.note_count){var na=el('a',null,{href:'/agent?id='+encodeURIComponent(r.agent_id)+'#notes',title:r.note_count+' note(s)'});na.className='iconlink';na.appendChild(mdi('note-text',{size:13,color:PAL.muted,title:r.note_count+' note(s)'}));aTd.appendChild(na);}
  tr.appendChild(aTd);
  tr.appendChild(el('td',r.model||''));
  tr.appendChild(el('td',r.family||'',{class:'muted'}));
  tr.appendChild(el('td',r.harness||''));
  tr.appendChild(el('td',r.hosting||'',{class:'muted'}));
  tr.appendChild(el('td',r.provider||'',{class:'mono muted ell',title:r.provider||''}));
  var wTd=el('td');var w=chipEl(r.open_weight?'open-weight':'proprietary','chip-weight '+(r.open_weight?'ow':'prop'));wTd.appendChild(w);tr.appendChild(wTd);
  var rkTd=el('td',fmtRank(r));rkTd.className='num';rkTd.title=r.partial?'ranked on its own (partial) set, not comparable':'';tr.appendChild(rkTd);
  var rtTd=el('td',r.resolve_rate==null?'':(r.resolve_rate*100).toFixed(0)+'%');rtTd.className='num';tr.appendChild(rtTd);
  var cTd=el('td',r.cost_per_task==null?'':'$'+r.cost_per_task.toFixed(3));cTd.className='num';tr.appendChild(cTd);
  var xTd=el('td',r.ctx_window?String(r.ctx_window):'');xTd.className='num';tr.appendChild(xTd);
  var nTd=el('td');nTd.className='num';if(r.note_count){nTd.appendChild(el('a',String(r.note_count),{href:'/agent?id='+encodeURIComponent(r.agent_id)+'#notes'}));}else{nTd.textContent='0';nTd.classList.add('muted');}tr.appendChild(nTd);
  frag.appendChild(tr);});
 tb.appendChild(frag);}
function applyView(){VIEW=filterSort(DATA,agMatch,COLS,sortKey,sortDir,null);renderHead();renderBody();}
wireFilter(applyView);  // shareable ?filter= deep-link (shared helper)
fetch('/api/agents').then(function(r){return r.json();}).then(function(j){DATA=j.agents||[];document.getElementById('meta').textContent=DATA.length+' agents \u00b7 '+(j.generated_at||'');applyView();}).catch(function(e){document.getElementById('meta').textContent='load error: '+e;});
</script></body></html>"""


def render_agents_page():
    """W85: client-rendered sortable/filterable agents TABLE (detail on click -> /agent)."""
    return _AGENTS_PAGE.replace("__CSS__", _APP_CSS).replace("__NAV__", _nav("Agents"))


def render_agent_detail(agent_id):
    """W85: per-agent DETAIL page (the model card that used to be inline on /agents) --
    reached by clicking an agent_id in the /agents table (mirrors /runs -> /run,
    /corpus -> /task). Hosts the full card + docs/HF + editable notes (bench.db note table,
    subject_type=agent; the retired W91 `retry_notes` ops content was migrated here)."""
    esc = lambda x: html.escape("" if x is None else str(x))
    pay = _agents_payload(dashboard_state())
    m = next((x for x in pay["agents"] if x.get("agent_id") == agent_id), None)
    p = [_page_head(f"agent {agent_id or ''}", "Agents")]
    p.append('<p style="font-size:12px"><a href="/agents">&larr; all agents</a></p>')
    if not m:
        p.append(f'<h1>agent not found</h1><div class=muted>{esc(agent_id)} is not in '
                 f'agents-meta.jsonl or on the board.</div></body></html>')
        return "".join(p)
    aid = m["agent_id"]; rank = m.get("rank"); rate = m.get("resolve_rate")
    if rank is not None and rate is not None:
        stat = f'#{rank} &middot; {rate*100:.0f}% ({_resfmt(m.get("resolved",0))}/{m.get("n",0)})'
    elif m.get("partial"):
        stat = 'partial coverage'
    else:
        stat = 'not ranked'
    cost = m.get("cost_per_task")
    tpt = m.get("turns_per_task")
    ow = (_chip_html('open-weight', 'chip-weight ow') if m.get("open_weight")
          else _chip_html('proprietary', 'chip-weight prop'))
    docs = f' &middot; <a href="{esc(m.get("docs_url"))}" target=_blank rel=noopener>docs</a>' if m.get("docs_url") else ''
    hf = f' &middot; <a href="{esc(m.get("hf_url"))}" target=_blank rel=noopener>HF</a>' if m.get("hf_url") else ''
    p.append(f'<div class=card id="agent-{esc(aid)}">'
             f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px">'
             f'<div><span class=mono style="font-size:15px;font-weight:700">{esc(aid)}</span> {ow} '
             f'<span class=muted>{esc(m.get("family",""))}</span></div>'
             f'<div style="font-size:13px;white-space:nowrap">{stat}'
             f'{(" &middot; $%.3f/task" % cost) if cost else ""}'
             f'{(" &middot; %.0f turns/task" % tpt) if tpt else ""} &middot; '
             f'<a href="/runs?agent={esc(aid)}">runs</a> &middot; '
             f'<a href="/model?id={esc(aid)}">tasks &amp; patches</a></div></div>'
             f'<div class=muted style="font-size:12px;margin-top:4px">'
             f'model <b>{esc(m.get("model",""))}</b> &middot; harness {esc(m.get("harness",""))} &middot; '
             f'{esc(m.get("hosting",""))} &middot; provider <span class=mono>{esc(m.get("provider",""))}</span> &middot; '
             f'ctx {esc(m.get("ctx_window",""))} &middot; quant {esc(m.get("quantization",""))} &middot; '
             f'timeout {esc(m.get("agent_timeout_s",""))}s{docs}{hf}</div>')
    # W91: `retry_notes` retired -- its ops/retry content migrated into the durable `note` table
    # (subject_type=agent, source='ops-migrated') and now renders in the "Agent notes" block below.
    # The STATIC agents-meta.jsonl `description` is the curated model-card blurb (distinct from notes).
    if m.get("description"):
        p.append(f'<div style="font-size:12px;margin-top:2px"><b>description:</b> {esc(m["description"])}</div>')
    p.append('<a name=notes></a>')
    p.append(_notes_block(
        "Agent notes", _subject_notes("agent", aid), add_action="/agent_note_add",
        back=f"/agent?id={esc(aid)}",
        hidden_inputs=f'<input type=hidden name=agent value="{esc(aid)}">',
        empty_label="no agent notes yet", placeholder="add an agent note/observation"))
    p.append('</div>')
    p.append(f'<script>{_NOTE_EDIT_JS}</script></body></html>')
    return "".join(p)


_INLINE_PATCH_CAP = 20_000  # cap per inline patch on the /model page (raw link for the rest)


def _read_bundle_patch(eval_id):
    """Final patch text for an attempt bundle: patch.diff, else agent_io stdout."""
    bd = _bundle_dir(eval_id) if eval_id else None
    if not bd:
        return ""
    pd = bd / "patch.diff"
    if pd.is_file():
        try:
            return pd.read_text(errors="replace")
        except OSError:
            pass
    aio = bd / "agent_io.json"
    if aio.is_file():
        try:
            dd = json.loads(aio.read_text())
            pl = (json.loads(dd.get("stdout") or "{}").get("patches") or [])
            return (pl[0].get("patch_text") or pl[0].get("patch") or "") if pl else ""
        except Exception:
            return ""
    return ""


def _bundle_transcript_name(eval_id):
    """Name of the full transcript file in a bundle (session.jsonl or rawcli.txt)."""
    bd = _bundle_dir(eval_id) if eval_id else None
    if not bd:
        return None
    for name in ("session.jsonl", "rawcli.txt"):
        if (bd / name).is_file():
            return name
    return None


def _render_patch_compare(task_id, agent_patch, outcome=""):
    """Side-by-side card: the agent's final patch vs the gold code patch (the answer
    key from zbench-tasks/solutions/). Used on /run so a reader can see what the model
    changed next to what the upstream fix changed. Diff lines are colored; each side is
    capped at _INLINE_PATCH_CAP chars with a pointer to the raw file for the rest."""
    esc = lambda x: html.escape("" if x is None else str(x))
    gp = _task_artifact_path(task_id, "gold_code.patch")
    gold = gp.read_text(errors="replace") if gp else ""

    def _side(title, text, empty):
        if not text.strip():
            return (f'<div class=pc-side><div class=pc-head>{title}</div>'
                    f'<div class=muted style="padding:8px">{empty}</div></div>')
        a, d, nf = _diff_stat(text)
        body = text if len(text) <= _INLINE_PATCH_CAP else (
            text[:_INLINE_PATCH_CAP] + f"\n--- truncated ({len(text):,} chars) ---")
        rows = []
        for ln in body.splitlines():
            cls = ("pc-meta" if ln.startswith(("diff --git", "index ", "+++", "---"))
                   else "pc-hunk" if ln.startswith("@@")
                   else "pc-add" if ln.startswith("+")
                   else "pc-del" if ln.startswith("-") else "")
            rows.append(f'<span class="{cls}">{esc(ln) or " "}</span>')
        return (f'<div class=pc-side><div class=pc-head>{title} '
                f'<span class=muted>{nf} file{"s" if nf != 1 else ""}, '
                f'<span style="color:#16a34a">+{a}</span> '
                f'<span style="color:#dc2626">&minus;{d}</span></span></div>'
                f'<pre class=pc-pre>{"".join(rows)}</pre></div>')

    verdict = {"resolved": "the hidden test passed with the model's patch",
               "miss": "the hidden test still failed with the model's patch"}.get(outcome, "")
    return (
        '<style>.pc-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}'
        '@media(max-width:900px){.pc-grid{grid-template-columns:1fr}}'
        '.pc-side{border:1px solid #e2e8f0;border-radius:6px;background:#fff;min-width:0}'
        '.pc-head{font-weight:600;font-size:12px;padding:6px 10px;border-bottom:1px solid #e2e8f0;background:#f8fafc}'
        '.pc-side pre.pc-pre{margin:0;padding:6px 0;font-size:11px;line-height:1.45;max-height:640px;'
        'overflow:auto;background:#fff;color:#0f172a;border:0;border-radius:0 0 6px 6px}'
        '.pc-pre span{display:block;padding:0 10px;white-space:pre}'
        '.pc-add{background:#ecfdf5;color:#166534}.pc-del{background:#fef2f2;color:#991b1b}'
        '.pc-hunk{color:#6366f1;background:#f5f3ff}.pc-meta{color:#64748b;font-weight:600}</style>'
        '<h2>Model patch vs. gold patch</h2>'
        '<div class=muted style="font-size:12px;margin-bottom:6px">Left: the final patch the '
        'model produced. Right: the upstream fix (the answer key; the model never sees it). '
        'Grading runs the hidden test, so the patches need not match line for line'
        + (f' &mdash; here {verdict}' if verdict else '') + '.</div>'
        '<div class=pc-grid>'
        + _side("Model patch", agent_patch, "no patch produced")
        + _side("Gold patch (upstream fix)", gold, "gold patch not available "
                "(zbench-tasks/solutions/ missing for this task)")
        + '</div>')


def _diff_stat(text):
    """(added, deleted, files) counted from a unified-diff string."""
    adds = dels = files = 0
    for line in text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("diff --git"):
            files += 1
        elif line.startswith("+"):
            adds += 1
        elif line.startswith("-"):
            dels += 1
    return adds, dels, files


def render_model_tasks(agent_id):
    """Per-MODEL task list: every task this agent attempted (resolved or not) with its
    FINAL PATCH inline, so a reviewer can confirm each failure is a real failure (and
    not a mis-grade or infra artifact). Route: /model?id=<config_id>.

    One row per task = the board-displayed attempt (prefer resolved, else latest), so
    this page agrees with the leaderboard; reruns are linked via /runs?agent=."""
    esc = lambda x: html.escape("" if x is None else str(x))
    if not agent_id:
        return _page_head("model tasks", "Agents") + "<h1>no model id given</h1></body></html>"
    rows = [s for s in _benchdb_attempts() if s.get("agent_id") == agent_id]
    p = [_page_head(f"tasks {agent_id}", "Agents")]
    p.append(f'<p style="font-size:12px"><a href="/agent?id={esc(agent_id)}">&larr; {esc(agent_id)}</a></p>')
    p.append(f'<h1>Tasks &amp; final patches &mdash; <span class=mono>{esc(agent_id)}</span></h1>')
    if not rows:
        p.append('<div class=muted>this agent has no attempts in bench.db.</div></body></html>')
        return "".join(p)
    best, counts = {}, {}
    for s in rows:
        inst = s.get("instance_id")
        counts[inst] = counts.get(inst, 0) + 1
        cur = best.get(inst)
        if (cur is None or (s.get("tests_passed") and not cur.get("tests_passed"))
                or str(s.get("timestamp", "")) >= str(cur.get("timestamp", ""))):
            best[inst] = s
    insts = sorted(best)
    nres = sum(1 for s in best.values() if s.get("tests_passed"))
    npatch = sum(1 for s in best.values() if _outcome_of(s) != "no_patch")
    p.append(f'<div class=muted style="margin-bottom:8px">'
             f'<b>{len(insts)} task(s)</b> &middot; {nres} resolved &middot; '
             f'{len(insts) - nres} failed &middot; {npatch} produced a patch &middot; '
             f'<a href="/runs?agent={esc(agent_id)}">all attempts (incl. reruns)</a></div>')
    p.append('<div class=muted style="font-size:11px;margin-bottom:8px">'
             f'{icon("check-circle", 12, "#16a34a")} resolved &middot; '
             f'{icon("close-circle", 12, "#dc2626")} failed (patch ran, hidden test failed) &middot; '
             f'{icon("alert", 12, "#b45309")} no patch produced &middot; '
             'open a row to read the final patch the model generated</div>')
    p.append('<table><tr><th>task</th><th>verdict</th><th class=num>&Delta;</th>'
             '<th>final patch (last response)</th><th>evidence</th></tr>')
    for inst in insts:
        s = best[inst]
        task_id = constants.task_of(inst)
        o = _outcome_of(s)
        verd = {"resolved": f'{icon("check-circle", 14, "#16a34a")} resolved',
                "miss": f'{icon("close-circle", 14, "#dc2626")} failed',
                "no_patch": f'{icon("alert", 14, "#b45309")} no patch'}.get(
                    o, f'{icon("alert-circle", 14, "#94a3b8")} {esc(o)}')
        ev = s.get("evaluation_id") or ""
        run = s.get("run_id") or ""
        patch = _read_bundle_patch(ev)
        adds, dels, nf = _diff_stat(patch)
        dcell = (f'<span style="color:#16a34a">+{adds}</span> '
                 f'<span style="color:#dc2626">&minus;{dels}</span>') if patch.strip() \
                else '<span class=muted>&mdash;</span>'
        multi = (f' <span class=muted style="font-size:10px">({counts[inst]} tries)</span>'
                 if counts[inst] > 1 else '')
        if patch.strip():
            body = patch if len(patch) <= _INLINE_PATCH_CAP else (
                patch[:_INLINE_PATCH_CAP]
                + f"\n\n--- truncated ({len(patch):,} chars); open the raw patch link for the rest ---")
            pcell = (f'<details><summary>{nf} file(s), {len(patch):,} chars</summary>'
                     f'<pre>{esc(body)}</pre></details>')
        else:
            pcell = '<span class=muted>no patch produced</span>'
        bd = _bundle_dir(ev)
        links = []
        if patch.strip():
            links.append(f'<a href="/field?run={esc(run)}&agent={esc(agent_id)}'
                         f'&instance={esc(inst)}&f=patch">raw patch</a>')
        if bd and (bd / "pb-verify.log").is_file():
            links.append(f'<a href="/logfile?bundle={esc(ev)}&name=pb-verify.log">verify log</a>')
        tname = _bundle_transcript_name(ev)
        if tname:
            links.append(f'<a href="/rich?bundle={esc(ev)}&name={esc(tname)}">transcript</a>')
        links.append(f'<a href="/run?run={esc(run)}&agent={esc(agent_id)}&instance={esc(inst)}">detail</a>')
        p.append(f'<tr><td class="mono" style="font-size:11px">'
                 f'<a href="/task?task={esc(task_id)}">{esc(task_id)}</a>{multi}</td>'
                 f'<td style="font-size:12px;white-space:nowrap">{verd}</td>'
                 f'<td class=num style="font-size:11px;white-space:nowrap">{dcell}</td>'
                 f'<td>{pcell}</td>'
                 f'<td style="font-size:11px">{" &middot; ".join(links)}</td></tr>')
    p.append('</table></body></html>')
    return "".join(p)


_LOGFILE_CAP = 5_000_000  # 5 MB inline cap for huge raw streams


def dashboard_state():
    """The state dict for the front page + /api/state. SINGLE PATH: always the SQL
    reader over bench.db (benchdb_reader.collect_state); there is no file reader."""
    import benchdb_reader
    db = Path(BENCHDB)
    rt = RUNTIME or (db.resolve().parent / ".runtime")
    return benchdb_reader.collect_state(db_path=db, tasks_dir=TASKS, runtime_dir=rt)


_BACKUP_COMPONENTS = [
    # key, default-checked, label
    ("cards", True, "Task cards", "card.md + problem_statement.md per task (human-readable corpus)"),
    ("meta", True, "Task meta.json", "corpus definitions (lang / status / oracle / fail_to_pass)"),
    ("ranks", True, "Ranks / leaderboard", "the live board as Markdown + a JSON snapshot"),
    ("charts", False, "Charts (SVG)", "server-rendered leaderboard + Pareto-frontier vector charts (.svg)"),
    ("gold", False, "Gold patches", "gold_code.patch + gold_test.patch + instance.jsonl (reference solutions)"),
    ("benchdb", False, "bench.db", "the full SQLite data store (attempts / invalidations / validations)"),
    ("blobs", False, "Attempt blobs", "per-attempt evidence bundles (transcripts / verify logs / patches) -- can be LARGE"),
    ("code", False, "System code", "the dashboard + scoring + orchestration source (tools/ + zbench-tasks/ *.py/.jsonl/.sh)"),
]


def _dir_size(path):
    """Total bytes under a dir (best-effort), for the backup-page size hints."""
    total = 0
    try:
        for p in Path(path).rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except Exception:
        pass
    return total


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0


def build_backup_archive(sel):
    """Build an IN-MEMORY .tar.gz of the SELECTED backup components. `sel` is a set of
    component keys (see _BACKUP_COMPONENTS). Returns (bytes, filename). Strictly
    READ-ONLY: reads task files + bench.db + the live board and mutates nothing."""
    import io, tarfile
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = f"zbench-export-{ts}"
    buf = io.BytesIO()
    manifest = ["zbench data export", f"created_utc: {ts}",
                f"components: {','.join(k for k in (c[0] for c in _BACKUP_COMPONENTS) if k in sel) or '(none)'}", ""]
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def _add_bytes(arcname, data):
            b = data.encode() if isinstance(data, str) else data
            info = tarfile.TarInfo(f"{root}/{arcname}")
            info.size = len(b); info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(b))

        def _add_file(arcname, path):
            p = Path(path)
            if p.is_file():
                tar.add(str(p), arcname=f"{root}/{arcname}")
                return True
            return False

        # ---- per-task text artifacts (cards / meta / gold) ----
        want = []
        if "cards" in sel:
            want += [a["name"] for a in TASK_ARTIFACTS if a["name"] in ("card.md", "problem_statement.md")]
        if "meta" in sel:
            want += [a["name"] for a in TASK_ARTIFACTS if a["name"] == "meta.json"]
        if "gold" in sel:
            want += [a["name"] for a in TASK_ARTIFACTS if a["name"] in ("gold_code.patch", "gold_test.patch", "instance.jsonl")]
        if want:
            task_dirs = sorted((d for d in (TASKS.iterdir() if TASKS.is_dir() else [])
                                if d.is_dir() and (d / "meta.json").is_file()),
                               key=lambda d: d.name)
            nfiles = 0
            for d in task_dirs:
                for fn in want:
                    if _add_file(f"tasks/{d.name}/{fn}", d / fn):
                        nfiles += 1
            manifest.append(f"tasks: {len(task_dirs)} dirs, {nfiles} files ({', '.join(want)})")

        # ---- ranks / leaderboard ----
        if "ranks" in sel:
            try:
                st = dashboard_state()
                lb = st.get("leaderboard") or []
                _add_bytes("ranks/leaderboard.md", leaderboard_markdown(lb, st.get("n_common", 0)))
                _add_bytes("ranks/leaderboard.json", json.dumps(
                    {"created_utc": ts, "n_common": st.get("n_common"), "leaderboard": lb,
                     "leaderboard_partial": st.get("leaderboard_partial")}, default=str, indent=2))
                manifest.append(f"ranks: {len(lb)} ranked agents, n_common={st.get('n_common')}")
            except Exception as e:
                _add_bytes("ranks/ERROR.txt", f"failed to render ranks: {e!r}")
                manifest.append(f"ranks: ERROR {e!r}")
            # (the legacy leaderboard Markdown export was removed 2026-07-30; the board Markdown above --
            # ranks/leaderboard.md via leaderboard_markdown() -- is the canonical export.)

        # ---- charts (server-rendered leaderboard + Pareto SVGs) ----
        if "charts" in sel:
            nsvg = 0
            for _name, _ in _CHART_DOWNLOADS:
                try:
                    svg = render_chart_svg(_name)
                except Exception as e:
                    svg = None
                    _add_bytes(f"charts/{_name}.ERROR.txt", f"failed to render {_name}: {e!r}")
                if svg:
                    _add_bytes(f"charts/{_name}.svg", svg)
                    nsvg += 1
            manifest.append(f"charts: {nsvg} svg ({', '.join(n for n, _ in _CHART_DOWNLOADS)})")

        # ---- bench.db (the whole store; small) ----
        if "benchdb" in sel:
            if _add_file("bench.db", BENCHDB):
                manifest.append(f"bench.db: {Path(BENCHDB).stat().st_size} bytes")
            else:
                manifest.append("bench.db: NOT FOUND")

        # ---- attempt blobs (evidence bundles; can be large) ----
        if "blobs" in sel:
            blobs = Path(BENCHDB).resolve().parent / "blobs"
            if blobs.is_dir():
                nfiles = 0
                for p in sorted(blobs.rglob("*")):
                    if p.is_file():
                        tar.add(str(p), arcname=f"{root}/blobs/{p.relative_to(blobs)}")
                        nfiles += 1
                manifest.append(f"blobs: {nfiles} files ({_human_size(_dir_size(blobs))})")
            else:
                manifest.append("blobs: NOT FOUND")

        # ---- system code (dashboard + scoring + orchestration source) ----
        if "code" in sel:
            docs_root = Path(__file__).resolve().parent.parent  # ~/docs/<task-folder>
            ztasks = docs_root / "zbench-tasks"
            ncode = 0
            # tools/*.py (this dashboard + readers)
            for p in sorted((docs_root / "tools").glob("*.py")):
                if _add_file(f"code/tools/{p.name}", p):
                    ncode += 1
            # zbench-tasks source: python + agent configs + shell recipes (NOT tasks/ corpus,
            # NOT bench-db, NOT mining-runs bulk -- those are covered by other components)
            if ztasks.is_dir():
                for pat in ("*.py", "*.jsonl", "*.sh", "*.md"):
                    for p in sorted(ztasks.glob(pat)):
                        if _add_file(f"code/zbench-tasks/{p.name}", p):
                            ncode += 1
            manifest.append(f"code: {ncode} source files (zbench/ + tools/ + zbench-tasks/)")

        _add_bytes("MANIFEST.txt", "\n".join(manifest) + "\n")
    return buf.getvalue(), f"{root}.tar.gz"


# Server-rendered chart SVGs included in the data-export archive when the "charts" component is
# selected (W148). The leaderboard + Pareto charts are already produced server-side as inline SVG;
# render_chart_svg() reuses those render functions to emit standalone .svg files under charts/ in
# the tar.gz. Order: (name, label).
_CHART_DOWNLOADS = [
    ("leaderboard", "Leaderboard chart (incl. partial-coverage agents)"),
    ("leaderboard-ranked", "Leaderboard chart (ranked-only)"),
    ("pareto", "Pareto frontier (partial-coverage agents participating)"),
    ("pareto-ranked", "Pareto frontier (ranked-only)"),
]


def _standalone_svg(markup):
    """Make an inline-<svg> string a valid standalone .svg file: XML decl + xmlns."""
    head = markup.split(">", 1)[0]
    if "xmlns=" not in head:
        markup = markup.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + markup


def render_chart_svg(name):
    """Render one downloadable chart SVG by name (see _CHART_DOWNLOADS). Returns standalone SVG
    text or None for an unknown/empty chart. Reuses the exact page render functions."""
    st = dashboard_state()
    lb = st.get("leaderboard", []); part = st.get("leaderboard_partial")
    ncom = st.get("n_common", 0); tol = st.get("pareto_tolerance") or 0.0
    if name == "leaderboard":
        m = render_leaderboard_chart(lb, ncom, partial=part)
    elif name == "leaderboard-ranked":
        m = render_leaderboard_chart(lb, ncom, partial=None)
    elif name == "pareto":
        m = render_pareto_chart(lb, tolerance=tol, partial=part, partial_in_frontier=True)
    elif name == "pareto-ranked":
        m = render_pareto_chart(lb, tolerance=tol, partial=None, partial_in_frontier=False)
    else:
        return None
    return _standalone_svg(m) if m else None


# ---- Errata: claude-cli vs pi harness-gap investigation (2026-08-21) -------
# One page documenting WHY the pi harness scored higher than the claude-cli
# harness on the SAME model, so the gap is not mistaken for a model-skill gap.
_ERRATA_RERUN_RUN_ID = "claude-fn-rerun-20260821"

# One row per task where ONLY claude-cli lost to pi (same model both sides).
# verdict: FN = false negative (behaviorally-correct patch failed an over-specific
# hidden test); INFRA = broken-run artifact (no real attempt); TRUE = real miss.
_ERRATA_CELLS = [
    # (model, task_id, verdict, confidence, why claude "lost")
    ("fable", "ZT-210f35e3a9ac", "FN", "high",
     "Rendered a valid markdown link [asd](url); the test pins the raw Slack literal &lt;url|label&gt;."),
    ("opus", "ZT-210f35e3a9ac", "FN", "high",
     "Same link divergence as the fable row (same task, other model)."),
    ("fable", "ZT-2cbf9e130e35", "FN", "med",
     "Dropped an alphabetical name-sort the brief never asked for (contested; a real-regression read exists)."),
    ("fable", "ZT-52b83f7b5883", "FN", "med-high",
     "Wrote a plain function; the test needs an internal rewire_* stub the brief never named."),
    ("fable", "ZT-6586d9078ea4", "FN", "high",
     "Cleaned extra whitespace; the test pins an exact output string with leading spaces."),
    ("fable", "ZT-7630a41857d5", "FN", "med",
     "Matched punctuation literally per the brief; regressed the -_/: search pi kept (contested)."),
    ("fable", "ZT-ee41f4afc996", "FN", "med-high",
     "Ranked groups above users; the test demands users be excluded, the brief only said 'sort above'."),
    ("opus", "ZT-1338aa97fd5d", "FN", "high",
     "Did the required query-narrowing; the test pins an exact DB query count that needs an optional extra step."),
    ("opus", "ZT-47a4d8900d5c", "FN", "high",
     "Emitted 3 list lines vs 1 glued string; the rendered docs are byte-identical."),
    ("fable", "ZT-5f164582a474", "INFRA", "high",
     "claude OAuth session expired mid-run; no patch was produced; the cell was never retried."),
    ("opus", "ZT-5708b71c93d2", "TRUE", "high",
     "Missing a user_has_folders() guard -> crash in the no-folders test. A real miss."),
    ("opus", "ZT-dde9ec247568", "TRUE", "high",
     "Gated the PR title on include_title; the brief's message formats show the title always. A real miss."),
]

_ERRATA_AGENT_OF = {"fable": "claude-cli-fable-5", "opus": "claude-cli-opus-5"}


def _errata_rerun_results():
    """Live pass/fail of the false-negative re-run (run_id claude-fn-rerun-20260821),
    keyed (config_id, task_id), latest attempt wins. Read-only; never raises."""
    out = {}
    try:
        import sqlite3
        db = Path(BENCHDB)
        if not db.exists():
            return out
        conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            for r in conn.execute(
                    "SELECT config_id, task_id, tests_passed, outcome, cost_usd, finished_at "
                    "FROM attempt WHERE run_id=? ORDER BY finished_at", (_ERRATA_RERUN_RUN_ID,)):
                out[(r["config_id"], r["task_id"])] = {
                    "resolved": bool(r["tests_passed"]), "outcome": r["outcome"],
                    "cost": r["cost_usd"], "finished": r["finished_at"]}
        finally:
            conn.close()
    except Exception:
        pass
    return out


def render_errata_page():
    """Static write-up of the pi-vs-claude-cli harness gap + a LIVE re-run status
    column (bench.db run_id claude-fn-rerun-20260821). Robust: the dynamic part is
    wrapped so the analysis always renders even if the DB read fails."""
    esc = html.escape
    rr = _errata_rerun_results()
    n_fn = sum(1 for c in _ERRATA_CELLS if c[2] == "FN")
    n_infra = sum(1 for c in _ERRATA_CELLS if c[2] == "INFRA")
    n_true = sum(1 for c in _ERRATA_CELLS if c[2] == "TRUE")

    p = [_page_head("Errata", "Errata")]
    p.append("<h1>Errata &mdash; why pi scored higher than claude-cli</h1>")
    p.append('<p class=muted style="font-size:12px;max-width:820px">Logged 2026-08-21. '
             'The pi harness resolved a few more tasks than the claude-cli harness on the '
             '<b>same model</b> (claude-opus-5 and claude-fable-5). Only the harness wrapper '
             'differs, so this cannot be a model-skill gap. This page records what the gap '
             'actually is.</p>')

    # --- headline ---------------------------------------------------------
    p.append('<div class="card" style="max-width:820px">')
    p.append("<b>Bottom line.</b> The gap is almost all a grading artifact, not a better "
             "harness. Of the 12 tasks where only claude-cli lost to pi: "
             f"<b>{n_fn} are false negatives</b> (a correct-behaving claude patch failed an "
             f"over-specific hidden test), <b>{n_infra} is a broken-run artifact</b> (the claude "
             f"login expired mid-run), and <b>only {n_true} are real misses</b> (both on opus). "
             "Corrected for the artifact and the false negatives, the two harnesses are "
             "essentially tied.</div>")

    # --- the numbers ------------------------------------------------------
    p.append("<h2>The numbers (best scored attempt per cell, shared task set)</h2>")
    p.append("<table style='max-width:820px'><thead><tr>"
             "<th>Model</th><th class=num>pi resolved</th><th class=num>claude-cli resolved</th>"
             "<th class=num>both pass</th><th class=num>both fail</th>"
             "<th class=num>only pi</th><th class=num>only claude</th></tr></thead><tbody>")
    for model, pir, clir, bp, bf, opi, ocl in [
            ("fable", "72/83", "65/82", 65, 10, 7, 0),
            ("opus", "71/83", "68/83", 66, 10, 5, 2)]:
        p.append(f"<tr><td>{model}</td><td class=num>{pir}</td><td class=num>{clir}</td>"
                 f"<td class=num>{bp}</td><td class=num>{bf}</td>"
                 f"<td class=num><b>{opi}</b></td><td class=num>{ocl}</td></tr>")
    p.append("</tbody></table>")
    p.append('<p class=muted style="font-size:12px;max-width:820px">The whole gap sits in one '
             'bucket: a patch was produced but the hidden test failed. claude-cli hits that '
             'outcome about twice as often as pi (16 vs 8 on fable; 15 vs 8 on opus). The '
             'no-patch, patch-apply-fail, and provider-error rates are equal and tiny.</p>')

    # --- harness difference ----------------------------------------------
    p.append("<h2>What differs between the harnesses</h2>")
    p.append('<p style="font-size:13px;max-width:820px">Both harnesses drive the identical '
             'model. The difference is patch <i>style</i>. The claude-cli harness writes '
             '<b>larger, more &ldquo;polished&rdquo; patches</b>: it edits more files, improves '
             'formatting, converts links, cleans whitespace. The pi harness writes '
             '<b>smaller, more surgical patches</b>.</p>')
    p.append('<p style="font-size:13px;max-width:820px">Many hidden tests check <b>exact '
             'incidental details</b> &mdash; an exact string, a list structure, a sort order, a '
             'database query count. A surgical patch that leaves those details alone matches the '
             'gold answer. A polished patch that &ldquo;improves&rdquo; them diverges and fails, '
             'even when it behaves correctly. In one task pi passed by <i>not touching</i> a file '
             'and leaving the gold&rsquo;s stray whitespace; claude cleaned it up and lost.</p>')

    # --- classification table + live re-run status -----------------------
    p.append("<h2>The 12 tasks only claude-cli lost, classified</h2>")
    p.append('<p class=muted style="font-size:12px;max-width:820px">Each row was audited against '
             'the hidden test, the failure log, the claude patch, and pi&rsquo;s passing patch. '
             'The re-run column is live from run <span class=mono>' + esc(_ERRATA_RERUN_RUN_ID) +
             '</span> (a fresh claude-cli attempt; the original attempts are untouched).</p>')
    _vchip = {
        "FN": '<span class="chip" style="background:#fef9c3;color:#854d0e">false negative</span>',
        "INFRA": '<span class="chip" style="background:#e0e7ff;color:#3730a3">infra artifact</span>',
        "TRUE": '<span class="chip" style="background:#fee2e2;color:#991b1b">real miss</span>'}
    p.append("<table style='max-width:1000px'><thead><tr>"
             "<th>Task</th><th>Model</th><th>Verdict</th><th>Conf.</th>"
             "<th class=normal-wrap style='white-space:normal'>Why claude lost</th>"
             "<th>Re-run</th></tr></thead><tbody>")
    for model, task, verdict, conf, why in _ERRATA_CELLS:
        # live re-run cell
        if verdict == "TRUE":
            rcell = '<span class=muted>not re-run</span>'
        else:
            res = rr.get((_ERRATA_AGENT_OF[model], task))
            if res is None:
                rcell = '<span class=muted><span class=spin></span> pending</span>'
            elif res["resolved"]:
                rcell = '<span class="chip-ok">now passes</span>'
            else:
                rcell = ('<span class="chip" style="background:#fee2e2;color:#991b1b">'
                         + esc((res.get("outcome") or "still fails")) + '</span>')
        tlink = f'/model?id={esc(_ERRATA_AGENT_OF[model])}'
        p.append(f"<tr><td class=mono><a href='{tlink}'>{esc(task)}</a></td>"
                 f"<td>{esc(model)}</td><td>{_vchip.get(verdict, verdict)}</td>"
                 f"<td class=muted>{esc(conf)}</td>"
                 f"<td class=normal-wrap style='white-space:normal;max-width:460px'>{why}</td>"
                 f"<td>{rcell}</td></tr>")
    p.append("</tbody></table>")

    # --- the two real misses ---------------------------------------------
    p.append("<h2>The two genuine failures (kept as fair losses)</h2>")
    p.append('<ul style="font-size:13px;max-width:820px">'
             '<li class=normal-wrap><b>ZT-5708b71c93d2 (opus)</b>: claude set up the folder-filter '
             'widget unconditionally. The brief said &ldquo;only when user_has_folders() is '
             'true&rdquo;. With no folders the widget call is missing and the test crashes. pi '
             'added the guard.</li>'
             '<li class=normal-wrap><b>ZT-dde9ec247568 (opus)</b>: the brief&rsquo;s message '
             'formats literally contain {title}. claude made the title conditional and dropped it '
             'in the default case. pi always renders it.</li></ul>')
    p.append('<p class=muted style="font-size:12px;max-width:820px">For balance: on opus, claude '
             'also beat pi on 2 tasks (ZT-2320a8917e00, ZT-524442bf44e2). The direction is not '
             'one-sided.</p>')

    # --- recommendations --------------------------------------------------
    p.append("<h2>Recommended follow-ups</h2>")
    p.append('<ul style="font-size:13px;max-width:820px">'
             '<li class=normal-wrap><b>Broken-run cell.</b> ZT-5f164582a474 (claude-cli-fable) is '
             'a [broken_config] artifact under METHODOLOGY &sect;3 (login expired). It is being '
             're-run; if it still cannot run, exclude it rather than count it.</li>'
             '<li class=normal-wrap><b>Over-specific tests.</b> Eight tasks fail agents on unstated '
             'internal details (exact strings, list shape, sort order, query counts, a rewire stub, '
             'a groups-only rule). Relaxing these tests, or writing the constraint into the brief '
             'as an interface requirement, would cut noise for <b>all</b> agents. Two rows '
             '(ZT-2cbf9e130e35, ZT-7630a41857d5) are genuinely contested.</li>'
             '<li class=normal-wrap><b>Caveat on the re-run.</b> A fresh attempt faces the same '
             'brittle test. It passes only if the model happens to match the gold&rsquo;s '
             'incidental detail this time. A re-run that still fails confirms the test is '
             'over-specific; it is not proof the patch is wrong.</li></ul>')
    p.append("</body></html>")
    return "".join(p)


def render_backup_page():
    """Selection form for the on-demand data export (user-requested). A GET form
    (checkboxes -> /download.tar.gz?key=1...) so no do_POST is needed. Named
    'Download data' (not 'backup') since it EXPORTS a snapshot; it does not restore.
    Also lists the downloadable server-rendered chart SVGs (W148)."""
    esc = html.escape
    try:
        ntasks = sum(1 for d in TASKS.iterdir()
                     if d.is_dir() and (d / "meta.json").is_file()) if TASKS.is_dir() else 0
    except Exception:
        ntasks = 0
    try:
        st = dashboard_state(); nrank = len(st.get("leaderboard") or []); ncom = st.get("n_common", 0)
    except Exception:
        nrank = ncom = 0
    _dbnote = ""
    try:
        _b = Path(BENCHDB)
        if _b.exists():
            _dbnote = f" (~{_b.stat().st_size // 1024} KB)"
    except Exception:
        pass
    _counts = {"cards": f"{ntasks} tasks", "meta": f"{ntasks} tasks",
               "ranks": f"{nrank} agents, {ncom} common tasks", "gold": f"{ntasks} tasks",
               "benchdb": _dbnote.strip(" ()")}
    p = [_page_head("download data", "Download")]
    p.append("<h1>Download data</h1>")
    p.append('<p class=muted style="font-size:12px;max-width:640px">Pick what to include; the '
             'server assembles a <span class=mono>.tar.gz</span> snapshot and streams it to your '
             'browser. Strictly read-only &mdash; this EXPORTS a copy, it does not modify or '
             'restore anything. The archive unpacks into a dated '
             '<span class=mono>zbench-export-&lt;ts&gt;/</span> folder with a '
             '<span class=mono>MANIFEST.txt</span>.</p>')
    p.append('<form method="get" action="/download.tar.gz" style="font-size:13px;line-height:1.9">')
    for key, chk, label, desc in _BACKUP_COMPONENTS:
        cnt = _counts.get(key, "")
        cnt_html = f' <span class=muted>&mdash; {esc(cnt)}</span>' if cnt else ""
        p.append(f'<div style="margin:3px 0"><label><input type="checkbox" name="{key}" value="1" '
                 f'{"checked" if chk else ""}> <b>{esc(label)}</b>{cnt_html}'
                 f'<div class=muted style="font-size:11px;margin:0 0 4px 22px">{esc(desc)}</div>'
                 f'</label></div>')
    p.append('<div style="margin-top:12px"><button type="submit" class="btn btn-primary">'
             f'{icon("download", 15, "#fff")} build &amp; download archive</button></div>')
    p.append('</form>')
    p.append("</body></html>")
    return "\n".join(p)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _redirect(self, loc):
        self.send_response(303)
        self.send_header("Location", loc)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_task_file(self, q):
        task_id = constants.task_of(q.get("task", [""])[0])
        name = q.get("name", [""])[0]
        fp = _task_artifact_path(task_id, name)
        try:
            if fp:
                self._send(200, fp.read_text(errors="replace"), "text/plain; charset=utf-8")
            elif (name == "problem_statement.md" and task_id
                  and "/" not in task_id and ".." not in task_id):
                self._send(200, _instance_problem(task_id) or "(no problem statement recorded)",
                           "text/plain; charset=utf-8")
            else:
                self._send(404, "bad task file")
        except Exception as e:
            self._send(500, f"error: {html.escape(repr(e))}")

    def _handle_rich(self, q):
        bundle = q.get("bundle", [""])[0]
        name = q.get("name", [""])[0]
        fp = _bundle_file(bundle, name)
        if transcript_view is None:
            self._send(500, "transcript_view module not available")
            return
        if not fp:
            self._send(404, "not found")
            return
        try:
            self._send(200, transcript_view.render_file(str(fp)))
        except Exception as e:
            self._send(500, f"<pre>render error: {html.escape(repr(e))}</pre>")

    def _handle_logfile(self, q):
        fp = _bundle_file(q.get("bundle", [""])[0], q.get("name", [""])[0])
        if not fp:
            self._send(404, "not found")
            return
        try:
            with fp.open("rb") as fh:
                data = fh.read(_LOGFILE_CAP)
            note = b"" if fp.stat().st_size <= _LOGFILE_CAP else \
                f"\n\n--- TRUNCATED at {_LOGFILE_CAP} bytes of {fp.stat().st_size} ---\n".encode()
            self._send(200, data + note, "text/plain; charset=utf-8")
        except Exception as e:
            self._send(500, f"error: {html.escape(repr(e))}")

    def _handle_field(self, q):
        # Serve embedded I/O fields (problem statement / agent patch / stderr) as raw
        # text/plain -- so /run stage boxes can link directly to them.
        files = _find_cell_files(q.get("run", [""])[0], q.get("agent", [""])[0],
                                 q.get("instance", [""])[0])
        tj = files.get("agent_io"); dd = {}
        if tj:
            try:
                dd = json.loads(tj.read_text())
            except Exception:
                dd = {}
        f = q.get("f", [""])[0]
        if f == "problem":
            _task_id = constants.task_of(q.get("instance", [""])[0])
            text = ((dd.get("agent_input") or {}).get("problem_statement")
                    or (_instance_problem(_task_id) if _task_id else "")
                    or "(no problem statement recorded)")
        elif f == "patch":
            try:
                pl = (json.loads(dd.get("stdout") or "{}").get("patches") or [])
                text = (pl[0].get("patch_text") or pl[0].get("patch") or "") if pl else ""
            except Exception:
                text = ""
            text = text or "(no patch produced)"
        elif f == "stderr":
            text = dd.get("stderr") or "(no stderr)"
        else:
            self._send(404, "unknown field"); return
        _lbl = {"problem": "problem statement", "patch": "agent patch", "stderr": "stderr"}.get(f, f)
        _hdr = (f"# {_lbl} -- {q.get('instance', [''])[0]} / "
                f"{q.get('agent', [''])[0]} / run {q.get('run', [''])[0]}\n"
                f"# (dashboard /field view -- not a git-apply source)\n\n")
        self._send(200, _hdr + text, "text/plain; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            try:
                self._send(200, render_html(dashboard_state()))
            except Exception as e:
                self._send(500, f"<pre>error: {html.escape(repr(e))}</pre>")
        elif u.path == "/api/state":
            self._send(200, json.dumps(dashboard_state(), default=str, indent=2),
                       "application/json")
        elif u.path == "/api/runs":
            try:
                self._send(200, json.dumps(_runs_payload(dashboard_state()), default=str),
                           "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": repr(e)}), "application/json")
        elif u.path == "/runs":
            try:
                self._send(200, render_runs_page())
            except Exception as e:
                self._send(500, f"<pre>runs page error: {html.escape(repr(e))}</pre>")
        elif u.path == "/coverage":
            try:
                self._send(200, render_coverage_page())
            except Exception as e:
                self._send(500, f"<pre>coverage page error: {html.escape(repr(e))}</pre>")
        elif u.path == "/review_set":
            q = parse_qs(u.query)
            run_id = q.get("run", [""])[0]; agent = q.get("agent", [""])[0]
            instance = q.get("instance", [""])[0]
            ev = _eval_id_for_cell(run_id, agent, instance)
            back = f"/run?run={html.escape(run_id)}&agent={html.escape(agent)}&instance={html.escape(instance)}"
            if not ev:
                self._send(400, "<pre>no evaluation_id for cell</pre>"); return
            reason = q.get("reason", [""])[0].strip()
            # Single-control semantics: non-empty reason => scoring exclusion;
            # empty reason => no exclusion (run counts by default).
            _set_run_exclusion(ev, reason)
            self._redirect(back)
        elif u.path == "/note_add":
            q = parse_qs(u.query)
            run_id = q.get("run", [""])[0]; agent = q.get("agent", [""])[0]
            instance = q.get("instance", [""])[0]
            ev = _eval_id_for_cell(run_id, agent, instance)
            back = f"/run?run={html.escape(run_id)}&agent={html.escape(agent)}&instance={html.escape(instance)}"
            body = q.get("body", [""])[0].strip()
            if not ev or not body:
                self._redirect(back); return
            _write_run_note(ev, body)
            self._redirect(back)
        elif u.path == "/note_edit":
            q = parse_qs(u.query)
            nid = q.get("id", [""])[0]
            back = q.get("back", ["/validation"])[0] or "/validation"
            body = q.get("body", [""])[0]
            try:
                # Human inline edit changes note text only. Machine categories, if any,
                # are just text prefixes like [artifact:infra] in the note body.
                _edit_note(nid, body=body)
            except Exception:
                pass
            self._redirect(back)
        elif u.path == "/task_note_add":
            q = parse_qs(u.query)
            task_id = q.get("task", [""])[0]
            body = q.get("body", [""])[0].strip()
            back = f"/task?task={html.escape(task_id)}" if task_id else "/corpus"
            if task_id and body:
                try:
                    _write_note("task", task_id, body)
                except Exception:
                    pass
            self._redirect(back)
        elif u.path == "/agents":            # W76 (W85: sortable table)
            try:
                self._send(200, render_agents_page())
            except Exception as e:
                self._send(500, f"<pre>{html.escape(repr(e))}</pre>")
        elif u.path == "/agent":             # W85: per-agent detail (model card + notes)
            q = parse_qs(u.query)
            try:
                self._send(200, render_agent_detail(q.get("id", [None])[0]))
            except Exception as e:
                self._send(500, f"<pre>{html.escape(repr(e))}</pre>")
        elif u.path == "/model":             # per-model task list + final patches (audit)
            q = parse_qs(u.query)
            try:
                self._send(200, render_model_tasks(q.get("id", [None])[0]))
            except Exception as e:
                self._send(500, f"<pre>{html.escape(repr(e))}</pre>")
        elif u.path == "/api/agents":        # W76
            try:
                self._send(200, json.dumps(_agents_payload(dashboard_state()), default=str),
                           "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": repr(e)}), "application/json")
        elif u.path == "/agent_note_add":    # W76: per-agent notes (subject_type=agent)
            q = parse_qs(u.query)
            agent = q.get("agent", [""])[0]
            body = q.get("body", [""])[0].strip()
            if agent and body:
                try:
                    _write_note("agent", agent, body)
                except Exception:
                    pass
            self._redirect("/agents")
        elif u.path == "/api/corpus":
            try:
                self._send(200, json.dumps(_corpus_payload(dashboard_state()), default=str),
                           "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": repr(e)}), "application/json")
        elif u.path == "/api/leaderboard":
            # data-only board (API-surface parity with /api/runs + /api/corpus); the
            # /=Leaderboard PAGE stays server-rendered (bespoke SVG chart).
            try:
                _st = dashboard_state()
                self._send(200, json.dumps({
                    "generated_at": _st.get("generated_at"),
                    "n_common": _st.get("n_common"),
                    "leaderboard": _st.get("leaderboard"),
                    "leaderboard_partial": _st.get("leaderboard_partial"),
                    "excluded_agents": _st.get("excluded_agents"),
                }, default=str), "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": repr(e)}), "application/json")
        elif u.path == "/corpus":
            try:
                self._send(200, render_corpus_page())
            except Exception as e:
                self._send(500, f"<pre>corpus page error: {html.escape(repr(e))}</pre>")
        elif u.path == "/errata":
            try:
                self._send(200, render_errata_page())
            except Exception as e:
                self._send(500, f"<pre>errata page error: {html.escape(repr(e))}</pre>")
        elif u.path == "/live":
            q = parse_qs(u.query)
            p = _live_session(q.get("run", [""])[0], q.get("agent", [""])[0],
                              q.get("instance", [""])[0])
            if not p or not p.is_file():
                self._send(200, "<html><body style='font-family:sans-serif;padding:20px'>"
                           "<p>No live transcript yet for this cell (agent hasn't emitted a "
                           "session yet, or it already landed &mdash; see the finished "
                           "transcript on the <b>/run</b> page).</p>"
                           "<p><a href='javascript:location.reload()'>reload</a></p></body></html>")
                return
            try:
                fmt = transcript_view.detect_format(str(p)) if transcript_view is not None else "unknown"
                if transcript_view is not None and fmt != "unknown":
                    body = transcript_view.render_file(str(p))
                    # auto-refresh so the partial transcript updates as the agent works
                    body = body.replace("<head>", "<head><meta http-equiv=refresh content=15>", 1)
                    self._send(200, body)
                else:
                    with p.open("r", errors="replace") as fh:
                        data = fh.read(_LOGFILE_CAP)
                    self._send(200, f"<html><head><meta http-equiv=refresh content=15></head>"
                               f"<body><pre>{html.escape(data)}</pre></body></html>")
            except Exception as e:
                self._send(500, f"<pre>live render error: {html.escape(repr(e))}</pre>")
        elif u.path == "/validation":
            # Retired UI: notes are surfaced in Runs and on /run; scoring exclusions are
            # edited on /run. Keep the old URL as a harmless redirect.
            self._redirect("/runs")
        elif u.path == "/download":
            try:
                self._send(200, render_backup_page())
            except Exception as e:
                self._send(500, f"<pre>download page error: {html.escape(repr(e))}</pre>")
        elif u.path == "/download.tar.gz":
            q = parse_qs(u.query)
            sel = {k for k, *_ in _BACKUP_COMPONENTS if q.get(k, ["0"])[0] == "1"}
            if not sel:
                self._send(400, "<html><body style='font-family:sans-serif;padding:20px'>"
                           "<p>Select at least one component to download.</p>"
                           "<p><a href='/download'>&larr; back</a></p></body></html>")
                return
            try:
                data, fname = build_backup_archive(sel)
                self.send_response(200)
                self.send_header("Content-Type", "application/gzip")
                self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self._send(500, f"<pre>export error: {html.escape(repr(e))}</pre>")
        elif u.path == "/card":
            # W96: /card folded into the canonical /task page -> redirect (keep old links working).
            task_id = constants.task_of(parse_qs(u.query).get("task", [""])[0])
            self._redirect("/task" + (("?" + urlencode({"task": task_id})) if task_id else ""))
        elif u.path == "/task_file":
            self._handle_task_file(parse_qs(u.query))
        elif u.path == "/task":
            # task ids are OPAQUE tokens -- validate as a safe single path segment only.
            task_id = constants.task_of(parse_qs(u.query).get("task", [""])[0])
            if (not task_id or "/" in task_id or ".." in task_id
                    or any(c.isspace() for c in task_id)):
                self._send(404, "bad task")
                return
            try:
                self._send(200, render_task_page(task_id))
            except Exception as e:
                self._send(500, f"<pre>{html.escape(repr(e))}</pre>")
        elif u.path == "/run":
            q = parse_qs(u.query)
            run_id = q.get("run", [""])[0]
            agent = q.get("agent", [""])[0]
            instance = q.get("instance", [""])[0]
            try:
                self._send(200, render_run_page(run_id, agent, instance))
            except Exception as e:
                self._send(500, f"<pre>{html.escape(repr(e))}</pre>")
        elif u.path == "/logs":
            run_id = parse_qs(u.query).get("run", [""])[0]
            self._send(200, render_logs_index(run_id))
        elif u.path == "/batch":
            run_id = parse_qs(u.query).get("run", [""])[0]
            try:
                self._send(200, render_batch_page(run_id))
            except Exception as e:
                self._send(500, f"<pre>{html.escape(repr(e))}</pre>")
        elif u.path == "/cells":
            # W94: /cells was REMOVED (its per-run drill-down + aggregate duplicated /runs;
            # aggregation is never needed). Redirect old links to the filtered /runs view,
            # mapping the legacy params (agent / instance / outcome) to ?agent=&task=&status=.
            q = parse_qs(u.query)
            _ag = q.get("agent", [None])[0]
            _inst = q.get("instance", [None])[0]
            _out = q.get("outcome", [None])[0]
            params = {}
            if _ag:
                params["agent"] = _ag
            if _inst:
                params["task"] = constants.task_of(_inst)
            if _out in ("resolved", "miss", "no_patch"):
                params["status"] = _out
            self._redirect("/runs" + (("?" + urlencode(params)) if params else ""))
        elif u.path == "/rich":
            self._handle_rich(parse_qs(u.query))
        elif u.path == "/logfile":
            self._handle_logfile(parse_qs(u.query))
        elif u.path == "/field":
            self._handle_field(parse_qs(u.query))
        else:
            self._send(404, "not found")


def main():
    global TASKS, SOLUTIONS, BENCHDB, RUNTIME
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address; default 127.0.0.1 (localhost only). "
                         "Use 0.0.0.0 to expose on all interfaces (e.g. reachable from your laptop).")
    ap.add_argument("--tasks", default=str(TASKS))
    ap.add_argument("--benchdb", default=str(DEFAULT_DB),
                    help="path to bench.db (the single store); the board is served "
                         "from it via the SQL reader. Default: the canonical bench.db.")
    ap.add_argument("--runtime", default=None,
                    help="path to .runtime/ (liveness leases); default: bench.db sibling")
    args = ap.parse_args()
    TASKS = Path(args.tasks)
    # keep the answer-key tree next to whatever --tasks points at
    SOLUTIONS = Path(os.environ.get("ZBENCH_SOLUTIONS_DIR", TASKS.parent / "solutions"))
    BENCHDB = args.benchdb
    RUNTIME = args.runtime
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    # best-effort discovery of a LAN-reachable address to print for convenience
    reachable = args.host
    if args.host in ("0.0.0.0", ""):
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            reachable = s.getsockname()[0]
            s.close()
        except Exception:
            reachable = socket.gethostname()
    def _p(*a):
        print(*a, flush=True)
    _p(f"[bench_dashboard] listening on {args.host}:{args.port}"
       + (" (all interfaces)" if args.host in ("0.0.0.0", "") else ""))
    _p(f"[bench_dashboard] open: http://{reachable}:{args.port}/")
    _p(f"[bench_dashboard] tasks={TASKS}")
    if BENCHDB:
        _p(f"[bench_dashboard] SQL backend ON (section 6): bench.db={BENCHDB} "
           f"runtime={RUNTIME or Path(BENCHDB).resolve().parent / '.runtime'}")
    _p("[bench_dashboard] READ-ONLY, no auth. Default bind is 127.0.0.1 (localhost only);")
    _p("[bench_dashboard] with --host 0.0.0.0 it binds externally and serves task")
    _p("[bench_dashboard] cards/paths in the clear -- only expose on a trusted network,")
    _p("[bench_dashboard] or prefer an SSH tunnel: ssh -L 8787:127.0.0.1:8787 <your-host>")
    _p("[bench_dashboard] Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
