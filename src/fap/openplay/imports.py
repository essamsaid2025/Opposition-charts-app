"""Open Play import controller.

The upload -> import workflow, delegating to the platform ImportService.
Streamlit-free: the uploaded-file object only needs ``.name``/``.read()``/
``.seek()`` (Streamlit's UploadedFile satisfies this, but so does io.BytesIO),
and the service is resolved through fap.openplay.runtime.
"""
from __future__ import annotations

from typing import Dict

import pandas as pd

from fap.core.exceptions import FAPError
from fap.openplay.config import COORD_SYSTEM_IDS
from fap.openplay.runtime import import_service
from fap.pipeline.importer import ImportResult


def read_uploaded_file(uploaded_file) -> pd.DataFrame:
    """Raw, un-normalized frame for the mapping preview.

    A widget adapter: it turns the uploaded file into bytes and hands them to
    ``ImportService.inspect``, which resolves the provider through the SAME path
    ``import_file`` uses - so the preview sees the exact provider the import will
    use (a StatsBomb export named ``events.json`` is recognized as StatsBomb
    here, not as generic JSON).
    """
    name = getattr(uploaded_file, "name", "") or "upload.csv"
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    data = uploaded_file.read()
    try:
        return import_service().inspect(data, name).frame
    except FAPError as exc:
        raise ValueError("Please upload a CSV, Excel or JSON file.") from exc


def platform_import(filename: str, data: bytes, mapping: Dict[str, str],
                    coord_mode: str, attack_direction: str) -> ImportResult:
    """Hand the confirmed Open Play mapping to the platform and let it do the
    work: provider detection, loading, mapping, coordinate normalization,
    cleaning, validation and quality scoring.

    Open Play's mapping is {canonical: source}; ImportService wants the inverse.
    """
    return import_service().import_file(
        data, filename,
        mapping={src: canon for canon, src in mapping.items() if src},
        coord_system=COORD_SYSTEM_IDS.get(coord_mode, "0-100"),
        flip_direction=attack_direction.startswith("Team attacks right-to-left"),
    )
