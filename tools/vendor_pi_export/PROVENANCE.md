# Vendored from @earendil-works/pi-coding-agent (MIT)

Files copied verbatim from a pi 0.81.1 installation
(`.../node_modules/@earendil-works/pi-coding-agent/dist/core/export-html`):
- template.html, template.css, template.js
- vendor/marked.min.js (MIT), vendor/highlight.min.js (BSD-3)

pi version: 0.81.1
Copied: 2026-07-27T05:10:55Z
Renderer is client-side: template.js reads base64 #session-data
{header, entries, leafId, ...} and renders. We generate sessionData in Python
(see ../transcript_view.py).

Update policy: keep exactly ONE pinned vendored snapshot. If pi's exporter must be
updated, replace these files in place and update this provenance record; do not add
parallel versions or copied experiments to the active tree.
