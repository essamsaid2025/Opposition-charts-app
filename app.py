"""Streamlit entrypoint: `streamlit run app.py`.

All wiring lives in fap.bootstrap, all rendering in fap.ui.

Path bootstrap: the project uses a src layout, and some hosts (or a bare
`streamlit run app.py` in a fresh clone) execute this file without the
package being pip-installed. If `fap` isn't importable, add ./src to
sys.path so the app runs identically installed or not.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import fap  # noqa: F401  (installed via `pip install -e .`)
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from fap.bootstrap import init_app
from fap.ui.shell import run

run(init_app())
