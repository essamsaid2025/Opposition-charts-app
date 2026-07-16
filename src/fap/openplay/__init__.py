"""Open Play engine business logic, migrated out of app.py.

Streamlit-free controllers and configuration for the Opponent Analysis screen:
data transforms, the upload/import workflow and the column-mapping controller.
The visualization engine itself stays in app.py (moving it would change the
charts, which the migration forbids).

Dependency direction: UI (app.py) -> these controllers -> platform services ->
pipeline -> providers. Nothing here imports Streamlit.
"""
from fap.openplay import config, runtime
from fap.openplay.imports import platform_import, read_uploaded_file
from fap.openplay.mapping import (
    _norm_key, alias_candidates, apply_column_mapping, auto_map_columns,
    mapping_confidence, mapping_log, mapping_preview_table, platform_detect,
    resolve_column_mapping, save_mapping_template,
)
from fap.openplay.transforms import (
    add_derived_columns, clean_columns, ensure_columns, flip_attacking_direction,
    is_success, normalize_coordinates, pct, safe_count, validate_data,
)

__all__ = [
    "config", "runtime",
    # imports
    "read_uploaded_file", "platform_import",
    # transforms
    "clean_columns", "ensure_columns", "validate_data", "normalize_coordinates",
    "flip_attacking_direction", "add_derived_columns", "pct", "safe_count", "is_success",
    # mapping
    "alias_candidates", "platform_detect", "auto_map_columns", "mapping_confidence",
    "save_mapping_template", "mapping_log", "resolve_column_mapping", "apply_column_mapping",
    "mapping_preview_table", "_norm_key",
]
