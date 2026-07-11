"""ImportService - the full Universal Data Engine pipeline:

    Raw file -> Provider plugin -> Column mapping (auto/template/manual)
    -> Coordinate detection & normalization -> Cleaning -> Canonical model
    -> Validation -> Quality score -> cached Ready Dataset

Normalized datasets are cached by content hash + options, so re-importing the
same file is instant.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field, replace
from io import BytesIO
from typing import Any

import pandas as pd

from fap.cache import CacheManager
from fap.core.exceptions import ProviderError
from fap.pipeline.cleaning import clean
from fap.pipeline.columns import ColumnMapping, detect_columns
from fap.pipeline.coordinates import detect_coordinate_system
from fap.pipeline.pipeline import DataPipeline
from fap.pipeline.quality import QualityScore, score
from fap.pipeline.templates import TemplateRepository
from fap.pipeline.validation import ValidationEngine, ValidationReport
from fap.providers.base import DataProvider, provider_registry

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImportResult:
    frame: pd.DataFrame
    provider_id: str
    mapping: dict[str, str]
    mapping_confidence: float
    coord_system: str
    coord_confidence: float
    validation: ValidationReport
    quality: QualityScore
    cleaning_log: list[str] = field(default_factory=list)
    template_used: str | None = None
    cache_hit: bool = False
    summary: dict[str, Any] = field(default_factory=dict)


class ImportService:
    def __init__(self, cache: CacheManager, templates: TemplateRepository,
                 pipeline: DataPipeline | None = None) -> None:
        self._cache = cache
        self._templates = templates
        self._pipeline = pipeline or DataPipeline()
        self._validator = ValidationEngine()

    # ------------------------------------------------------------ helpers
    def pick_provider(self, filename: str, provider_id: str | None = None) -> DataProvider:
        if provider_id:
            return provider_registry.create(provider_id)
        candidates = [cls() for cls in provider_registry]
        # vendor/manual plugins outrank the generic file catch-alls
        candidates.sort(key=lambda inst: inst.info.category == "file")
        for instance in candidates:
            if instance.supports(filename):
                return instance
        raise ProviderError(f"No provider recognizes {filename!r} - choose one explicitly.")

    def detect(self, raw_frame: pd.DataFrame) -> tuple[ColumnMapping, str | None]:
        """Auto column detection, preferring a saved template for this shape."""
        template = self._templates.find_by_signature([str(c) for c in raw_frame.columns])
        detected = detect_columns(raw_frame)
        if template:
            detected.mapping.update(template.mapping)
            for canonical in template.mapping.values():
                detected.confidence[canonical] = 1.0
            return detected, template.name
        return detected, None

    # ------------------------------------------------------------ main entry
    def import_file(self, data: bytes, filename: str, *, provider_id: str | None = None,
                    mapping: dict[str, str] | None = None, coord_system: str | None = None,
                    flip_direction: bool = False, options: dict[str, Any] | None = None,
                    use_cache: bool = True) -> ImportResult:
        provider = self.pick_provider(filename, provider_id)
        cache_key = self._cache_key(data, provider.info.id, mapping, coord_system,
                                    flip_direction, options)
        if use_cache:
            hit = self._cache.get(cache_key)
            if hit is not None:
                logger.info("Import cache hit for %s", filename)
                return replace(hit, cache_hit=True)

        raw = provider.load(BytesIO(data), filename, options=options)

        detected, template_used = self.detect(raw.frame)
        final_mapping = dict(raw.column_mapping)      # provider knowledge first
        final_mapping.update(detected.rename_dict())  # then auto/template detection
        if mapping:
            final_mapping.update(mapping)             # explicit user mapping wins

        # coordinate system: explicit > provider-declared > heuristic
        mapped_preview = raw.frame.rename(columns=final_mapping)
        heuristic_system, heuristic_conf = detect_coordinate_system(mapped_preview)
        if coord_system:
            system, conf = coord_system, 1.0
        elif raw.native_coord_system != "0-100":
            system, conf = raw.native_coord_system, 1.0
        else:
            system, conf = heuristic_system, heuristic_conf

        frame = self._pipeline.run(raw, flip_direction=flip_direction,
                                   column_mapping=final_mapping, coord_system=system)
        frame, cleaning_log = clean(frame)
        validation = self._validator.run(frame)
        quality = score(frame)

        result = ImportResult(
            frame=frame, provider_id=provider.info.id,
            mapping=final_mapping, mapping_confidence=detected.overall_confidence,
            coord_system=system, coord_confidence=conf,
            validation=validation, quality=quality, cleaning_log=cleaning_log,
            template_used=template_used,
            summary={
                "rows": int(len(frame)),
                "matches": int(frame["match_id"].astype(str).str.strip().replace("", pd.NA).nunique()),
                "players": int(frame["player"].astype(str).str.strip().replace("", pd.NA).nunique()),
                "teams": int(frame["team"].astype(str).str.strip().replace("", pd.NA).nunique()),
                "event_types": int(frame["event_type"].replace("", pd.NA).nunique()),
            },
        )
        self._cache.set(cache_key, result)
        return result

    def save_template(self, name: str, provider_id: str, raw_columns: list[str],
                      mapping: dict[str, str]) -> None:
        self._templates.save(name, provider_id, raw_columns, mapping)

    @staticmethod
    def _cache_key(data: bytes, provider_id: str, mapping: dict[str, str] | None,
                   coord_system: str | None, flip: bool, options: dict[str, Any] | None) -> str:
        h = hashlib.sha256(data)
        h.update(json.dumps([provider_id, mapping, coord_system, flip, options],
                            sort_keys=True, default=str).encode())
        return f"import::{h.hexdigest()[:40]}"
