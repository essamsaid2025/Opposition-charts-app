# First Team Football Analysis Platform (FAP)

Production-grade, plugin-based football analytics platform.
See `docs/ARCHITECTURE.md` for the full design.

## Run

    pip install -e ".[dev]"
    streamlit run app.py

## Test

    pytest -q

## Layout

    app.py                  entrypoint (3 lines)
    config/                 layered YAML configuration
    assets/themes/          themes as YAML data
    src/fap/core/           plugin engine, discovery, events, exceptions, types
    src/fap/config/         settings loader (defaults -> local -> env)
    src/fap/state/          typed namespaced session state
    src/fap/cache/          memory/disk cache, @cached, DataFrame hashing
    src/fap/db/             SQLite engine, migrations, repositories, models
    src/fap/auth/           pluggable authentication (local built in)
    src/fap/providers/      data provider plugins (csv/excel built in)
    src/fap/pipeline/       canonical schema, coordinate plugins, transforms, filters
    src/fap/metrics/        metric plugins
    src/fap/visuals/        visualization plugins + PitchFactory (empty by design)
    src/fap/analytics/      insight-rule plugins + engine
    src/fap/reports/        report sections + builder
    src/fap/exports/        export-format plugins (png/csv built in)
    src/fap/themes/         ThemeManager (YAML themes)
    src/fap/projects/       project save/load service
    src/fap/workspaces/     workspace service
    src/fap/ui/             shell, pages, reusable components, generic controls
    src/fap/utils/          small pure helpers
    tests/                  unit tests (headless, no Streamlit needed)
