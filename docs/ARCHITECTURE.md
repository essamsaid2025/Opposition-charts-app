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
