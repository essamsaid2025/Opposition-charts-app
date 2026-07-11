# FAP Architecture

## Layers (dependencies point downward only)

    fap.ui                     Streamlit pages, shell, reusable components, generic control renderer
    ─────────────────────────
    application services       ProjectService, WorkspaceService, ReportBuilder, InsightEngine
    ─────────────────────────
    domain                     pipeline (schema/transforms/filters), metrics, visuals, analytics
    ─────────────────────────
    infrastructure             providers, db + repositories, cache, auth, themes, config, logging
    ─────────────────────────
    fap.core                   plugin engine, discovery, events, exceptions, shared types

`fap.core` imports nothing from the app. Only `fap.ui` and `fap.state`
(guarded) import Streamlit, so the entire platform is testable headlessly.

## Plugin families

| Family            | Base class        | Registry            | Add by dropping a file in            |
|-------------------|-------------------|---------------------|--------------------------------------|
| Visualizations    | Visualization     | visual_registry     | fap/visuals/maps, fap/visuals/charts |
| Metrics           | Metric            | metric_registry     | fap/metrics/builtin                  |
| Providers         | DataProvider      | provider_registry   | fap/providers/builtin                |
| Exporters         | Exporter          | export_registry     | fap/exports/builtin                  |
| Coordinate systems| CoordinateSystem  | coord_registry      | fap/pipeline/coordinates.py (or new) |
| Insight rules     | InsightRule       | insight_registry    | fap/analytics                        |
| Report sections   | ReportSection     | section_registry    | fap/reports                          |
| Authenticators    | Authenticator     | auth_registry       | fap/auth                             |

Registration is decorator-based; `discover_plugins()` imports every module in
a plugin package at startup, so **adding a capability never edits existing
code** (Open/Closed). A faulty plugin is logged and skipped, never fatal.

## Key mechanisms

- **Canonical schema** (`fap.pipeline.schema`): providers output raw frames;
  the pipeline coerces/validates into one contract that every metric and
  visual consumes. One normalization point, N producers, M consumers.
- **Declarative controls** (`Control` in `fap.core.types`): plugins declare
  the widgets they need; `fap.ui.components.controls.render_controls` renders
  them generically. Zero per-chart UI code.
- **State** (`fap.state`): typed, namespaced StateManager over
  `st.session_state`; all keys inventoried in `fap/state/keys.py`; dict
  fallback for tests.
- **Cache** (`fap.cache`): backend strategy (memory LRU+TTL / disk pickle),
  content-hash keys for DataFrames, `@cached` decorator, config-selected.
- **Config** (`fap.config`): frozen dataclasses; defaults.yaml ->
  settings.local.yaml -> FAP_* env vars (FAP_DATABASE__PATH=...).
- **Persistence** (`fap.db`): SQLite + explicit append-only migrations;
  repositories are the only SQL; project/workspace payloads are versioned
  JSON documents so old saves survive upgrades.
- **Composition root** (`fap.bootstrap.init_app`): the single place concrete
  classes are constructed and injected via `AppContext` (DIP).

## Extension recipes

New pitch map: create `fap/visuals/maps/pressure_map.py`, subclass
`PitchVisualization`, declare `info` + `controls`, implement `render(ctx)`.
Done - it appears in the UI selector automatically.

New vendor feed: create `fap/providers/builtin/wyscout_provider.py`,
implement `supports()` + `load()`, return `RawDataset` with a
`column_mapping` and its native coordinate system id.

New export format: create `fap/exports/builtin/pdf_exporter.py`, implement
`can_export()` + `export()`.

## Universal Football Data Engine (Phase 4)

    Raw file -> Provider plugin -> Column mapping (auto / template / manual)
    -> Coordinate detection & normalization -> Cleaning -> Canonical event model
    -> Validation -> Quality score -> cached Ready Dataset -> FilterSet

- **Canonical schema** (`fap.pipeline.schema`): 30+ columns (match/season
  context, player/team, timing, event detail, xG/pass metrics, booleans).
  `end_x`/`end_y` are canonical; legacy `x2`/`y2` stay as synced aliases.
- **Column detection** (`fap.pipeline.columns`): alias tables + fuzzy matching
  per canonical field, per-field confidence, overall confidence gate that
  opens the wizard's manual-mapping UI.
- **Mapping templates** (`fap.pipeline.templates`, migration 3): saved
  mappings keyed by a signature of the source columns; auto-reapplied when
  the same file shape returns.
- **Coordinate systems** (`fap.pipeline.coordinates`): plugins for 0-100,
  120x80, StatsBomb, Opta, Wyscout, Metrica (0-1), 105x68 meters,
  SkillCorner / Second Spectrum (centered meters), Tracab (centered cm),
  plus `detect_coordinate_system()` heuristics over start AND end coords.
- **Providers** (`fap.providers.builtin`): generic CSV/Excel (delimiter,
  encoding, sheet and header auto-detected), StatsBomb JSON, Wyscout JSON,
  Opta F24 XML, Hudl CSV, Sportscode XML, Metrica CSV, SkillCorner JSON,
  Tracab CSV, Second Spectrum JSON/JSONL, Manual tagging. Vendor plugins
  outrank generic catch-alls in auto-selection.
- **Validation** (`fap.pipeline.validation`): rules are plugins
  (validation_registry) - missing columns, duplicates, invalid/out-of-range
  coordinates, impossible minutes/xG/distances, invalid periods, unknown
  event names, missing timestamps, high null percentages - collected into a
  ValidationReport with markdown rendering.
- **Quality score** (`fap.pipeline.quality`): weighted 0-100 across
  completeness, coordinate validity, player information, event consistency,
  timeline consistency.
- **Cleaning** (`fap.pipeline.cleaning`): whitespace/text normalization,
  event-synonym and outcome maps, boolean normalization, duplicate removal.
- **Filter engine** (`fap.pipeline.filters`): declarative, JSON-round-trip
  FilterSet over competition/season/match/team/opponent/player/period/
  minutes/event/outcome/body part/play pattern/set piece + custom
  (column, op, value) predicates. Every future chart consumes filtered
  canonical frames and implements no filtering of its own.
- **Performance**: one DataFrame copy per import (steps mutate in place);
  normalized ImportResults cached by content hash + options (200k-row file:
  ~5s cold, ~17ms cached; filters ~37ms).
- **Import wizard** (`fap.ui.pages.import_wizard`): 5 steps - source,
  preview + format detection, mapping (+templates), coordinates, import
  summary with progress, validation report and quality breakdown.
