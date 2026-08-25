# Report Studio Redesign — Canva-like Football Report Editor

Design document only. **No code was changed.** This is the deliverable of the
audit/design phase; implementation waits for approval.

Goal: rebuild Report Studio into a professional, Canva-like design editor for
football reports/presentations — drag/resize/rotate/group/layers/undo-redo,
rich text, images, first-class football chart objects, multi-page, templates,
brand kit, and multi-format export — **reusing** the existing FAP data,
analytics, chart engine, document model and export pipeline, without rewriting
the application and without touching the frozen xG model or xG integration.

---

## 1. Current Architecture Audit

### 1.1 Where Report Studio lives
| Layer | Location |
|---|---|
| Domain model | `src/fap/reports/models.py` (`ReportDocument`, `Cover`, `Section`, `Block`, `KPI`, `Table`, `Insight`, `Chart`, `ReportRecord`) |
| Page/layout overlay | `src/fap/reports/studio.py` (`ReportStudio`, `Page`, `BlockLayout`, `EditorState`, `page_size`) |
| Mutation API | `src/fap/reports/editor_ops.py` (move/resize/rotate/duplicate/delete/hide/lock/z-order/align/distribute/pages) |
| Render engine | `src/fap/reports/layout.py` (`LayoutEngine` → `RenderedDocument`, fractional geometry) |
| Publish settings | `src/fap/reports/publishing.py` (`PublishSettings`, `MasterPage`, `Watermark`, `Zone`, page numbering, tokens) |
| Per-block styling | `src/fap/reports/block_style.py` |
| Exporters | `src/fap/reports/exporters.py` + `_pdf.py` (matplotlib) + `_office.py` (docx/pptx) |
| Templates / build | `templates.py`, `builder.py`, `builders.py`, `sections.py`, `visual_section.py`, `builtin/*.py` |
| Persistence | `manager.py` (`ReportsManager`), `repository.py`, `registry.py` |
| AI extension points | `ai.py` (interfaces only — no implementation) |
| Editor UI (Streamlit) | `src/fap/ui/studio/` (`editor.py`, `covers.py`, `history.py`, `preview.py`, `sortable.py`) |
| Editor pages | `src/fap/ui/builtin/report_editor.py` (page id `report_editor`, "Report Studio"), `reports.py` (library) |
| Canvas component | `src/fap/ui/builtin/report_canvas.py` + `frontend/report_canvas/index.html` (232-line hand-written JS) |

### 1.2 Current frontend architecture
- Pure **Streamlit**. The editor is Streamlit widgets plus one custom HTML/JS
  component (`report_canvas`) declared via `streamlit.components.v1`.
- The canvas supports **drag, resize, snap** (no rotate, no marquee multi-select,
  no grouping, no in-canvas rich-text, no rulers/guides rendering, limited
  keyboard). It returns command batches (`{ts, commands}`) to Python via
  `setComponentValue`; Python applies `editor_ops` and **reruns the whole page**.
- Undo/redo exists in Python (`ui/studio/history.py`) over document snapshots.

### 1.3 Current rendering architecture
- One **pure** `LayoutEngine.build(document)` → `RenderedDocument` with
  resolution-independent geometry (each element box is a 0..1 fraction of its
  page). One model feeds five media (HTML %, PDF pt, PPTX EMU, DOCX width, MD).
- Charts are **references** (`Block.kind == "chart"`, payload `{viz_id, controls}`).
  `ReportsManager._materialize` renders them to PNG (`image_b64`) via the
  visuals engine before layout; the layout engine stays pure (no matplotlib).

### 1.4 How reports are stored
- `ReportRecord` (id, title, workspace/project/dataset, owner, contributors,
  status, version, `document` dict, timestamps) persisted via `repository.py`
  into the app DB (`user_data/fap.sqlite3`). The **whole `ReportDocument` dict**
  is stored, so the studio overlay (`meta["studio"]`) is saved/versioned/
  autosaved with **no schema change** and no second store.

### 1.5 How reports are exported
- `exporter_registry` plugins consume a `RenderedDocument`: **Markdown, HTML**
  (always available), **PDF** (matplotlib, always available), **DOCX/PPTX**
  (via `python-docx`/`python-pptx`, graceful "format unavailable" when absent).
- Export preserves layout, multi-page, embedded chart/image PNGs, per-block
  style, cover, headers/footers, watermark, page numbers.

### 1.6 Existing chart components
- `fap.visuals` engine: `visual_registry`, `Renderer`, `ExportEngine` (→ PNG),
  themes, `FilterSet`. Registered charts include Shot Map, Pass Map, Carry Map,
  heatmaps, Match Stats (Comparison), momentum/xT, shot profile, comparisons
  (static + Plotly), distributions, etc. (`fap/visuals/charts/*`, `maps/*`).
- The Open Play engine (`fap.openplay.engine`) exposes filters + `apply_filters`
  and `add_derived_columns` (which attaches canonical `internal_xg`).

### 1.7 Existing football visualizations
- Pitch maps (shot/pass/carry/defensive/heat/possession), goal renderer
  (`fap/visuals/goal.py`), set-piece visuals, tactical board (`fap.tactical`),
  Match Stats comparison, player dashboards, scouting charts (PyPizza), comparison
  charts. All are registry-driven and reusable as report objects **today** via the
  chart-reference block.

### 1.8 Existing data access APIs/functions
- `fap.ui.dataset_bridge.legacy_active_frame(ctx)` → the canonical active event
  frame (`WorkspaceManager.active_frame(user)` — single source of truth).
- `fap.openplay.engine` (`default_ctx`, `apply_filters`, `OPEN_PLAY_FILTERS`),
  `add_derived_columns` (canonical `internal_xg`), `fap.xg` (aggregation helpers).
- Teams/players/scouting services; `fap.datahub` import center.

### 1.9 Authentication / user storage
- Streamlit-native OIDC (`st.login/st.user`) + local auth (`fap.auth`), identity
  layer (`fap.identity`), capability/role engine, workspaces. Reports are
  workspace/owner scoped (`ReportRecord.owner/workspace_id/contributors`).

### 1.10 Current Streamlit limitations (why a redesign is needed)
- **Round-trip manipulation.** Every drag/resize/select posts to Python and
  triggers a full script rerun → no smooth 60fps direct manipulation, visible
  latency, and difficulty with continuous gestures (rotate, marquee, group drag).
- **No real design-editor primitives.** No multi-select marquee, grouping,
  rotate handles, alignment/snap guides rendered live, distribute UI, rich
  in-canvas text editing, per-character formatting, or robust keyboard shortcuts.
- **Layout thrash.** Streamlit reruns re-mount widgets; maintaining editor state,
  focus, and selection across reruns is fragile.
- **No infinite/zoomable canvas** with rulers/guides; zoom is a number, not a
  fluid viewport.
- These are structural to Streamlit's execution model; incremental fixes cannot
  reach a Canva-class UX.

### 1.11 Which parts can be reused (KEEP — high value)
- **Document model** (`ReportDocument`, `Block`, `Cover`, `Section`) and the
  **studio overlay** (`Page`, `BlockLayout`, `EditorState`) — already a complete,
  JSON-serializable, backward-compatible page/element model with x/y/w/h/z/
  rotation/locked/align and per-page size/orientation/background.
- **`editor_ops`** — a full, pure document-mutation API (move, resize, rotate,
  duplicate, delete, hide, lock, bring-forward/back/front/back, align, distribute,
  create/duplicate/delete/move/reorder pages, add block).
- **`LayoutEngine` + exporters** — the print-fidelity multi-format pipeline.
- **Chart-as-reference + `visuals` engine** — football objects that re-render
  from data (no screenshots) already exist.
- **Persistence, versioning, autosave** (`ReportsManager`), **templates**,
  **publish settings/masters/tokens**, **block_style**, **AI interfaces**.

### 1.12 Which parts should be replaced completely
- The **editor frontend**: `report_canvas` (HTML/JS component) and the Streamlit
  editor chrome in `ui/studio/*` and `ui/builtin/report_editor.py`. These are
  replaced by a dedicated interactive editor (see §4/§11). Everything in §1.11 is
  preserved and consumed by the new editor through an adapter.

---

## 2. Canva UX Analysis (what we are matching)
Canva Presentations' editor is defined by a small set of interaction guarantees:
- **Direct manipulation** on an infinite, zoomable canvas: click-select,
  marquee multi-select, drag, 8-handle resize, corner rotate, smart snapping to
  edges/centers/other elements with live guides, nudge with arrows.
- **Left panel** of content sources (Templates, Elements/Shapes, Text, Images,
  Uploads, plus domain content — here: Football, Charts).
- **Contextual right panel** that changes with the selection (position/size/
  rotation/opacity; typography; colors; borders; shadows; chart/data config).
- **Top bar**: name, undo/redo, preview, share, export.
- **Bottom**: page thumbnails, add/duplicate/delete/reorder pages.
- **Layers/grouping/lock/hide**, copy-paste-duplicate, keyboard shortcuts.
- **Templates** with editable + locked/brand-locked elements; **brand kit**.
- **Fast client-side render**; export to PNG/PDF/PPTX with fonts and images.
Our redesign targets each of these explicitly (§3, §4).

---

## 3. Editor-Engine Comparison

| Criterion | tldraw (React SDK) | Fabric.js (canvas lib) | Polotno (Konva/React SDK) |
|---|---|---|---|
| React integration | Native (React-first) | Framework-agnostic; wrap manually | Native React |
| Drag / select / resize / rotate | Built-in, polished | Built-in (rotate/scale/move) | Built-in, polished |
| Marquee multi-select | Built-in | Manual | Built-in |
| Grouping | Built-in | Group object (manual UI) | Built-in |
| Layers panel | Build (state exists) | Build | Built-in |
| Snapping / guides | Built-in | Manual | Built-in |
| Text editing / rich text | Built-in rich text | IText/Textbox (basic) | Rich text built-in |
| Fonts / sizes / colors | Yes | Yes (manual UI) | Yes (full UI) |
| Image handling / crop | Yes (crop basic) | Yes (manual crop) | Yes (crop built-in) |
| Undo/redo | Built-in | Manual (or plugin) | Built-in |
| Keyboard shortcuts | Extensive built-in | Manual | Extensive built-in |
| JSON document serialization | Store snapshot (JSON) | `toJSON`/`loadFromJSON` | JSON built-in |
| Custom shapes | **React component shapes** (ideal) | Custom classes / image objects | Custom element types |
| Custom football chart objects | Excellent (React shape → request PNG/SVG) | Good (image object bound to data) | Good (custom section/element) |
| Performance | Strong (virtualized) | Strong (canvas) | Strong (Konva) |
| PNG export | Yes | Yes (canvas → PNG) | Yes |
| PDF export | Compose (per-page PNG) | Compose (jsPDF) | **Built-in PDF** |
| PPTX export | Compose (server) | Compose (server) | Not native (server) |
| Licensing (see Licensing Validation below) | **Paid commercial license required for any commercial/internal product; production will not run without a valid license key**; hobby tier is non-commercial + watermark; pricing is sales-gated (non-public) | **MIT** (fully permissive, no key, no watermark, self-host) | **Commercial** (paid; self-serve from ~$899, enterprise low five figures; 60-day dev trial; built on Konva) |
| Maintainability | High (cohesive SDK) | Medium (you build the chrome) | High (turnkey) but vendor-coupled |
| FAP integration cost | New React build; adapter to `ReportDocument` | New React build + build all editor chrome | New React build; adapter; license |

Notes: FAP currently has **no React/Node toolchain** — components are hand-written
HTML/JS. Any of these adds a first Vite/React/TS build (contained to the editor).

---

## 4. Recommended Technology (UPDATED after licensing validation — see §4a)

**tldraw is NOT approved** for this product. A final validation against official
sources (§4a) found that the current tldraw SDK license requires a **paid
commercial license for any commercial or internal product**, and the SDK **will
not run in production without a valid license key**, with **non-public,
sales-gated pricing**. That is a material cost, legal, and vendor-lock risk and a
hard production gate for a commercial football-analytics product — i.e. exactly
the "licensing/cost issue that makes it unsuitable" case we were asked to guard
against. Polotno is likewise a **paid** commercial SDK.

**Approved recommendation: build the editor on a permissive MIT engine —
`Konva.js` with `react-konva` (primary), or `Fabric.js` (alternative) — as a
React micro-app embedded in FAP via a Streamlit custom component, with football
charts as custom data-bound shapes that request renders from the existing Python
visuals engine.**

Why Konva.js (+ react-konva):
- **MIT licensed**: free, self-hostable, no license key, no watermark, no
  per-seat cost, no vendor lock, and safe for commercial/SaaS distribution.
- It is the **same canvas engine Polotno is built on**, so it is proven capable
  of exactly this Canva-class design editor; its `Transformer` gives resize/
  rotate/multi-select handles, it has layers, high performance, and a clean
  React binding.
- **Custom shapes/groups** map perfectly to data-bound football objects
  (`{viz_id, dataSource, controls, style}` rendered from the Python engine).
- Store serializes to JSON → clean adapter to the existing `ReportDocument` +
  studio overlay (no export-pipeline rewrite; existing reports keep working).
- Trade-off (accepted): we build the editor **chrome** (side panels, layers UI,
  snapping guides, undo/redo — the domain `editor_ops`/history already exist to
  back it). This is more UI code than a turnkey SDK, but removes all licensing
  cost/risk and maximizes control over bespoke football components.

**Alternative A — Fabric.js (MIT):** also fully permissive; richer built-in
object controls (interactive move/scale/rotate/group, `toJSON`) out of the box,
but framework-agnostic (not React-native). A strong second choice if we prefer
more built-in object behavior over React-native ergonomics.

**Paid option — Polotno (only if budget approved):** the fastest path to a
literal Canva clone (turnkey panels/pages/templates/PNG+PDF export, built on
Konva). Transparent pricing (self-serve ~$899; enterprise low five figures).
Choose only if the team accepts a recurring commercial license + vendor coupling
in exchange for speed-to-parity. **Not the default**, given the goal of avoiding
licensing cost/lock-in.

**Not recommended — tldraw:** only reconsider if the team specifically wants
tldraw's UX and will purchase its (sales-gated) commercial license and accept the
production license-key requirement.

**Decision rule:** default to **Konva.js (MIT)**; use **Fabric.js (MIT)** if we
prefer its built-in object controls; consider **Polotno** only if a paid turnkey
SDK is explicitly approved; **avoid tldraw** for this commercial product.

---

## 4a. Licensing Validation (final, against official sources — Aug 2026)

Answers to the 10 required checks:

1. **Exact tldraw license:** the "tldraw SDK 3.x license." Tiers: **Trial**
   (100-day free eval), **Hobby** (non-commercial only, must display the "made
   with tldraw" watermark), **Commercial** (paid), plus development-only use
   without a key.
2. **Commercial SaaS/product use permitted?** Yes, **but only with a paid
   commercial license** — and "internal products at companies is considered
   commercial use," so it is not free for us.
3. **Watermark required for our use?** Under the hobby (non-commercial) license
   the watermark is mandatory. Our commercial use is not eligible for hobby, so
   we must license commercially regardless.
4. **Cost/terms to remove watermark / license commercially:** a Business/
   commercial license is required; **pricing is not public** ("contact sales,"
   startup pricing "may be available"). **The SDK will not work in production
   without a valid license key.**
5. **Restrictions (embedding / UI customization / custom React shapes /
   commercial distribution / self-hosting):** these are technically supported,
   but all gated behind the **paid commercial license** and the **production
   license-key requirement**; the hobby tier forbids commercial use outright.
6. **Do exported PDFs/images need extra licensing?** No separate export license
   was found — but export happens inside the SDK, which itself requires the paid
   production key to run, so exports are effectively gated by the same license.
7. **Can our Report JSON/document model stay independent of the engine's
   format?** **Yes — for every candidate.** Our plan keeps `ReportDocument` as
   the canonical persisted model and maps the engine's store via an adapter; no
   engine dictates our storage format. (Confirmed feasible for Konva/Fabric/tldraw.)
8. **Can the engine support our football chart objects as custom data-bound
   shapes?** **Yes — for all three.** Konva custom shapes/groups, Fabric custom
   objects, tldraw custom React shapes can each hold `{viz_id, dataSource,
   controls}` and render an image/SVG produced by the Python visuals engine.
9. **React/Streamlit integration:** a **dedicated React editor** embedded as a
   Streamlit custom component (iframe) is the right architecture for any engine;
   only document JSON + render intents cross the boundary (see §12).
10. **Performance for multi-page reports with many charts/images:** all engines
    are canvas-based and performant. Football charts render to **images
    (PNG/SVG)**, so the canvas holds image nodes, not live chart runtimes — cheap
    to draw. Mitigations: virtualize off-screen pages, cache `image_b64`, and
    render charts on demand server-side. No engine shows a performance blocker.

**Comparison of the three on licensing (the deciding factor):**
- **Konva.js — MIT** (free, no key, no watermark, self-host, commercial-safe).
- **Fabric.js — MIT** (same freedoms).
- **Polotno — paid** commercial SDK (~$899 self-serve+, built on Konva).
- **tldraw — paid** commercial SDK; **production blocked without a purchased
  license key**; pricing sales-gated.

**Licensing decision:** adopt a **permissive MIT engine (Konva.js primary,
Fabric.js alternative)** to eliminate licensing cost, production-key gating, and
vendor lock-in for the commercial product. tldraw and Polotno remain paid options
only if the team later approves a commercial SDK budget.

Sources: [tldraw SDK 3.x license](https://tldraw.dev/legal/tldraw-sdk-3-x-license),
[tldraw License docs](https://tldraw.dev/community/license),
[tldraw license-key docs](https://tldraw.dev/sdk-features/license-key),
[tldraw license-update blog](https://tldraw.dev/blog/license-update-for-the-tldraw-sdk),
[Polotno pricing](https://polotno.com/sdk/pricing),
[Polotno license](https://polotno.com/legal/license),
[Polotno vs Konva](https://polotno.com/sdk/product/compare/polotno-sdk-vs-konvajs),
[Open-source design SDKs comparison (IMG.LY)](https://img.ly/blog/open-source-design-editor-sdks-a-developers-guide-to-choosing-the-right-solution/).

---

## 5. Target UX

```
┌──────────────────────────────────────────────────────────────────────┐
│ TOP BAR:  [Report name ✎]   ⟲ Undo  ⟳ Redo   👁 Preview   💾 Save   ⤓ Export   🔗 Share │
├───────────┬──────────────────────────────────────────────┬───────────┤
│ LEFT      │ CENTER (infinite zoomable canvas)             │ RIGHT     │
│ SIDEBAR   │   • rulers + guides + snapping                │ CONTEXT   │
│ Templates │   • selection handles (resize/rotate)         │ PANEL     │
│ Elements  │   • marquee multi-select, drag, group         │ position  │
│ Text      │   • current Page rendered at Page size        │ size      │
│ Images    │                                               │ rotation  │
│ Charts    │                                               │ opacity   │
│ Football  │                                               │ typography│
│ Uploads   │                                               │ colors    │
│           │                                               │ borders   │
│           │                                               │ shadows   │
│           │                                               │ chart cfg │
│           │                                               │ data src  │
├───────────┴──────────────────────────────────────────────┴───────────┤
│ BOTTOM:  [◻ Page 1] [◻ Page 2] … [＋ Add] [⧉ Duplicate] [🗑 Delete]  (drag to reorder) │
└──────────────────────────────────────────────────────────────────────┘
```
- **Top bar**: report name (inline edit), undo/redo, preview (read-only render),
  save (persist via Python), export (PDF/PNG/JPG; PPTX future), share (reuse
  existing report sharing/contributors if present, else hidden).
- **Left sidebar tabs**: Templates, Elements (shapes/lines/dividers), Text
  (heading/paragraph/number styles), Images, Charts (registry viz), Football
  (Shot Map, Pass Map, Carry Map, Heatmap, Formation, Pitch, Player Card, Match
  Stats, xG chart, xG timeline, KPI card, comparison, table, pass network,
  tactical zones), Uploads (image upload → FileStorage).
- **Center**: infinite/zoomable canvas; the active Page is a fixed-size artboard;
  rulers/guides/snapping; selection/rotate handles; drag-drop from left panel.
- **Right context panel**: driven by selection type — geometry (x/y/w/h/rotation/
  opacity/lock/visible), typography (font/size/weight/line/letter/align/color),
  fills/borders/shadows, and for football/chart objects a **chart configuration**
  block (match/team/period/filters) + **data source** selector.
- **Bottom**: page thumbnails with add/duplicate/delete/reorder (drag).

---

## 6. Document Model (persisted, canonical)

Keep the existing `ReportDocument` as the **single persisted model** (backward
compatible; the whole export pipeline and all stored reports keep working). The
new editor operates on an in-browser editor store and maps to/from this model
through an adapter. Normalized shape the editor guarantees:

```
Report (ReportDocument)
├─ id, title, template_id, meta, export_settings
├─ cover (Cover)                       # generated cover page
├─ brand_ref                           # meta["brand"] -> BrandKit id (new, §7)
├─ pages[]  (studio overlay: Page)     # size, orientation, background, kind
└─ elements[] (Block + BlockLayout)    # one per page via layout.page_id
     ├─ id, kind (text|image|chart|qr|football|shape|group)   # kinds extended
     ├─ x, y, width, height, rotation, z, locked, hidden, opacity
     ├─ align, style (block_style: font/size/weight/color/…)
     └─ payload:
         • text     -> { text, variant, richText? }
         • image    -> { image_id | image_b64, fit, radius, caption }
         • shape    -> { shape, fill, stroke, radius }          # new kind
         • chart    -> { viz_id, controls, dataSource, image_b64(cache) }
         • football -> alias of chart with a football viz_id + dataSource
         • group    -> { children: [element_id...] }            # new kind
```

Notes:
- `x/y/w/h/z/rotation/locked/align` already exist on `BlockLayout`; `hidden` on
  `Block`; `opacity`/`style` via `block_style` and element content. New additions
  (`shape`, `group` kinds, `dataSource` sub-object, `opacity` on layout) are
  **additive** and default-safe (old reports load unchanged, per the overlay's
  existing versioning story).
- The **AI-future** requirement (§10) is satisfied: the model is fully declarative
  JSON, so an AI layer can emit `pages[]`/`elements[]`/`dataSource`/`text` directly.

---

## 7 (of doc §4 requirement). Football Element Model

Football objects are **chart-reference elements** (kind `chart`/`football`) whose
payload carries a `dataSource` and `controls`, rendered by the existing
`fap.visuals` engine — never screenshots. Changing config re-renders.

```json
{
  "kind": "football",
  "payload": {
    "viz_id": "shot_map",
    "dataSource": { "datasetId": "…", "matchId": "…", "team": "Barcelona", "period": "full_match" },
    "controls": { "filters": {…}, "theme": "…" },
    "style": { "width": 480, "height": 320 },
    "image_b64": "…cache…"
  }
}
```

Catalog (all map to existing/registered viz or existing services):
- Basic: text, heading, paragraph, shape, line, divider (text/shape kinds).
- Media: image, player image, team/club logo (image kind + FileStorage/brand).
- Football: Shot Map, Pass Map, Carry Map, Heatmap, Formation, Pitch, Player
  Card, **Match Stats** (uses canonical `internal_xg` for xG/NPxG — never goals/
  provider), xG chart, xG timeline, KPI card, comparison chart, table, pass
  network, tactical zones (from `fap.tactical`).

Each football object **retains** match/team/period/filters/size/style/dataSource;
editing config → Python re-renders via `ExportEngine` (PNG now; SVG upgrade
later for crispness). No analytics are duplicated in the editor.

---

## 8. Data Binding Architecture

- Every chart/football element stores a **`dataSource`** (datasetId, matchId,
  team, period, filters) — a reference, not embedded results.
- Rendering: editor emits a `renderElement(id, viz_id, dataSource, controls,
  size, theme)` intent → Python resolves the frame via `legacy_active_frame`/
  `WorkspaceManager` (+ `add_derived_columns` for canonical `internal_xg`) →
  renders via `fap.visuals` `Renderer`/`ExportEngine` → returns PNG/SVG bytes →
  editor updates the shape (and caches `image_b64` on the element for offline/
  export). xG **always** from `internal_xg`; no duplicated calculations.
- **Auto-population tokens** (core product requirement): text and dataSource
  fields support tokens resolved against a selected match/dataset:
  `{{home_team}} {{away_team}} {{home_score}} {{away_score}} {{home_xg}}
  {{away_xg}} {{shot_map}} {{xg_timeline}} {{match_stats}}`.
  - The layout/publish layer **already** resolves furniture tokens
    (`{club}`, `{opponent}`, `{date}`, `{n}`) — we extend the same resolver to
    block text and to a "bind match" action that fills tokens and sets each
    football element's `dataSource` from the chosen match. Selecting a match
    re-materializes all bound elements.

---

## 9. Template System

Reuse and extend `fap.reports.templates`:
- Start blank; choose template; edit; **save as template**; duplicate; multi-page;
  reuse; **replace data while keeping layout** (apply a new match to a template's
  tokens + dataSources).
- **Locked vs editable elements**: `BlockLayout.locked` already exists; brand/logo/
  background elements are marked locked (and brand-bound); text/charts/images/stats
  are editable. Templates persist the studio overlay (pages + layouts + locks) +
  blocks + `brand_ref` + token bindings.
- Categories: Match Report, Opposition Report, Team Report, Player Report, Post
  Match Report, Tactical Report (seed a few; the P3 Opposition Report builder and
  builtin sections provide content scaffolds to convert into templates).

---

## 10. Brand System (Brand Kit)

New concept, workspace/org-scoped, stored under `meta["brand"]` / a `BrandKit`
record; consumed by templates, cover design, master pages and `block_style`:
- Colors: primary, secondary, accent, background (+ text/muted).
- Fonts: heading, body, number (Google Fonts / bundled).
- Logos: club, organization; icons.
- Templates **inherit** the active brand kit; brand-locked elements resolve their
  fill/font/logo from it. Ties into existing `fap.theme` + `LayoutEngine.branding`.

---

## 11 (doc §8). Export Architecture

- **Keep server-side print-fidelity export** (existing `LayoutEngine` →
  `exporter_registry`): PDF (matplotlib), HTML, Markdown, DOCX/PPTX (optional).
  Multi-page, fonts-where-possible, embedded charts/images, cover/furniture.
- **Add quick client export** from the canvas: PNG/JPG per page (and multi-page
  PDF by composing page rasters) for fast "download this design".
- **PPTX**: already stubbed via `python-pptx`; architected for the future — each
  page → a slide, each element → a positioned shape/picture (EMU geometry already
  produced by the layout engine).
- Both paths consume the **same** `ReportDocument`, so client and server exports
  agree. Charts export from the cached `image_b64`/freshly materialized PNG/SVG.

---

## 12 (doc §11). Architecture Recommendation (Streamlit vs React)

**Report Studio becomes a dedicated React editor embedded in FAP as a Streamlit
custom component (iframe). The rest of FAP stays Streamlit. Do NOT rewrite the app.**

- **Stays in Streamlit / Python (unchanged):** app shell, navigation, auth
  (`st.login`/`fap.auth`/identity/capabilities), reports **library** page, data
  access (`WorkspaceManager`/`legacy_active_frame`/openplay), chart rendering
  (`fap.visuals`), analytics (xG via `internal_xg`), persistence
  (`ReportsManager`/`repository`), templates, **server export pipeline**
  (`LayoutEngine` + exporters), brand kit storage.
- **Moves to React (inside the iframe editor):** interactive canvas — selection,
  drag/resize/rotate, grouping, layers, snapping/guides, rich text, panels,
  page thumbnails, live preview.
- **Communication (Streamlit-native, no new server routes):**
  - **Load:** Python passes the report JSON (adapted from `ReportDocument`) +
    catalog (fonts, viz list, brand kit) as component args.
  - **Save/mutate:** JS posts the updated document JSON (or op batches) via
    `setComponentValue` → Python persists through `ReportsManager` (unchanged
    versioning/autosave). Debounced/interval save to avoid rerun storms.
  - **Chart render:** JS emits a `renderElement` intent → Python renders via the
    visuals engine → returns bytes on the next component arg cycle; the element
    caches `image_b64`. (Chart-config changes are infrequent, so the round-trip
    is acceptable — unlike drag, which stays fully client-side.)
- **Report persistence:** unchanged model + store; the adapter maps editor JSON ↔
  `ReportDocument`/overlay, so **existing reports open in the new editor** and
  vice-versa within the shared model.
- **Export pipeline:** unchanged server path remains the source of print truth;
  client PNG/PDF added for speed.
- **Authentication / data access:** unchanged — the iframe inherits the Streamlit
  session; all data/render requests go back through Python (no direct DB/data
  access from JS), preserving capability scoping and the canonical-data rule.

---

## 13. Migration Strategy (parallel, feature-flagged, reversible)

1. **Parallel page.** Add a new page `report_studio_v2` ("Report Studio (new)")
   behind a feature flag/capability. The existing `report_editor` stays fully
   available and unmodified until v2 is proven. No removal until sign-off.
2. **Shared model.** v2 reads/writes the **same** `ReportDocument` via an adapter;
   any v2-only editor state lives additively under `meta["studio_v2"]` (old
   exporters ignore it; old editor still works). **No data migration** required.
3. **Chart parity first.** v2 renders football objects through the existing
   `fap.visuals` engine so output matches today's reports.
4. **Cutover.** When v2 reaches parity + passes acceptance (§16), flip the default
   page; keep v1 reachable for one release; then retire v1.
5. **Rollback.** Because the model is shared and additive, disabling the flag
   returns users to v1 with all reports intact.

---

## 14. Phased Implementation Plan

For each phase: affected/new files, deps, risks, tests, migration.

**Phase A — Editor foundation (React shell + component bridge)**
- New: `src/fap/ui/builtin/frontend/report_studio/` (Vite+React+TS, **Konva +
  react-konva**, MIT), `src/fap/ui/builtin/report_studio.py` (component decl +
  Python bridge), page `report_studio_v2` (flagged). Adapter stub
  `reports/editor_adapter.py`.
- Deps: Node/Vite/React/TS + **konva/react-konva (MIT)** (build-time only; ships
  static assets). **No paid SDK, no license key.**
- Risks: first Node toolchain in repo; iframe↔Streamlit messaging.
- Tests: adapter round-trip (`ReportDocument` ↔ editor JSON) Python tests; smoke
  render of the component; flag on/off leaves v1 untouched.
- Migration: additive; v1 unchanged.

**Phase B — Pages / document model in the editor**
- Affected: `editor_adapter.py`, `studio.py`/`editor_ops.py` (reused, not
  changed). New: React page store + bottom page-thumbnail UI.
- Risks: keeping page ids stable with the overlay.
- Tests: create/duplicate/delete/reorder pages ↔ overlay; legacy report opens.

**Phase C — Text / images / shapes**
- Affected: `block_style.py` (reuse), FileStorage upload path. New: React text,
  image, shape shapes; right-panel typography/fill/border/shadow.
- Risks: rich-text ↔ `block_style`/markdown mapping fidelity.
- Tests: style round-trips into all exporters; image upload → element; export
  parity vs v1 for text/image.

**Phase D — Football chart objects**
- Affected: `report_studio.py` bridge `renderElement`; `fap.visuals` engine
  (reuse). New: React chart/football shapes; chart-config right panel.
- Deps: none new (reuse ExportEngine). Risks: render round-trip latency; SVG later.
- Tests: shot_map/match_stats element renders; xG uses `internal_xg`; config
  change re-renders; export embeds the cached PNG.

**Phase E — Templates**
- Affected: `templates.py` (extend). New: template gallery in left panel; "save
  as template", "replace data keeping layout".
- Risks: locked/brand elements semantics.
- Tests: apply template → pages/elements; locked elements immovable; save/load
  template; replace-data preserves layout.

**Phase F — Data binding + auto-population**
- Affected: extend token resolver (layout/publish) to block text + dataSource;
  "bind match" action. New: match/dataset picker in editor.
- Risks: token/dataSource resolution correctness; canonical-data rule.
- Tests: `{{home_xg}}` etc. resolve from a selected match; binding sets football
  dataSources; xG from `internal_xg` only; empty/invalid match handled.

**Phase G — Brand system**
- New: `BrandKit` model + storage; brand panel; template inheritance; wire into
  `block_style`/cover/masters/`theme`.
- Risks: precedence (brand vs per-element style).
- Tests: brand kit apply/inherit; brand-locked element resolves brand values;
  export reflects brand.

**Phase H — Export**
- Affected: exporters (reuse); add client PNG/JPG/PDF; PPTX hardening.
- Risks: client vs server fidelity divergence; font embedding.
- Tests: PDF/PNG/JPG multi-page; charts/images/fonts preserved; server vs client
  agree on layout; PPTX slide-per-page.

**Phase I — Polish / performance / testing**
- Snapping/guides tuning, keyboard shortcuts, large-report performance, autosave
  debounce, accessibility, and full regression. Cutover + retire v1.

---

## 15. Risks

- **Licensing** — RESOLVED (§4a): use MIT **Konva.js/Fabric.js** to avoid
  tldraw's paid commercial license + production license-key gate and Polotno's
  paid license. Revisit only if a paid SDK budget is later approved.
- **First Node/React toolchain** in a Python/Streamlit repo — contained to the
  editor, but adds a build step and CI consideration.
- **Streamlit ↔ iframe messaging** latency for chart renders — mitigated by
  keeping manipulation fully client-side and only round-tripping config changes.
- **Model drift** between editor JSON and `ReportDocument` — mitigated by a
  single adapter with round-trip tests and the shared canonical model.
- **Scope creep** — enforce parity-first, feature-flag, and keep v1 until proven.
- **Fonts in export** — embed a curated font set for PDF/PPTX fidelity.
- **Do-not-touch rules** — xG stays canonical `internal_xg`; no analytics
  duplication; no changes to the frozen model or unrelated FAP features.

---

## 16. Acceptance Criteria

1. New editor (v2) available behind a flag; **v1 untouched and reversible**.
2. Canva-class interactions: multi-select, drag, 8-handle resize, rotate,
   group/ungroup, lock/unlock, hide/show, layers, snapping+guides, undo/redo,
   duplicate/delete, keyboard shortcuts, zoom/pan.
3. Multi-page: add/duplicate/delete/reorder; per-page size/orientation/background.
4. Text (fonts/sizes/weights/colors/alignment), images (upload/crop/fit), shapes.
5. **Football objects are real editable elements** (not screenshots) that retain
   match/team/period/filters/size/style and **re-render on config change** via
   the existing engine; xG from **canonical `internal_xg`** only.
6. Templates: start blank/from template, edit, save-as-template, duplicate,
   replace-data-keeping-layout; locked/brand elements respected.
7. Auto-population: selecting a match fills `{{…}}` tokens and binds football
   objects' data sources.
8. Brand kit: colors/fonts/logos inherited by templates and brand-locked elements.
9. Export: PDF + PNG + JPG multi-page preserving layout/fonts/charts/images;
   PPTX architected (slide-per-page) and available when deps present.
10. Persistence/versioning/autosave via the unchanged `ReportsManager`; existing
    reports open in v2 through the adapter.
11. No regressions in unrelated FAP features; full app test suite green (same
    pre-existing set); the xG model/integration untouched.
12. Document model remains declarative JSON capable of being AI-populated later.

---

### Do-not rules honored by this design
Frozen xG model & xG integration untouched; xG only from canonical `internal_xg`;
no duplicated football analytics; no full-app rewrite; existing Report Studio
preserved until the replacement is proven; parallel/feature-flagged; existing
chart/data/services reused throughout.

**STOP — awaiting approval before any implementation.**
