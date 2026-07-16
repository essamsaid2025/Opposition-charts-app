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
from fap.pipeline import schema
from fap.pipeline.cleaning import clean
from fap.pipeline.columns import ColumnMapping, detect_columns
from fap.pipeline.coordinates import detect_coordinate_system
from fap.pipeline.pipeline import DataPipeline
from fap.pipeline.quality import QualityScore, score
from fap.pipeline.templates import TemplateRepository
from fap.pipeline.validation import ValidationEngine, ValidationReport
from fap.providers.base import DataProvider, RawDataset, provider_registry
from fap.providers.custom import CUSTOM_PREFIX, CustomProviderRepository, temporary_custom_provider
from fap.providers.intelligence import DetectionReport, ProviderIntelligence

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FilePreview:
    """The provider decision and the raw frame it produces, without importing.

    This is the front stage of ``import_file`` made observable: a caller that
    needs to look at a file before committing to the full import (the mapping
    preview, the wizard) consumes this instead of resolving a provider itself.
    Because it comes from the same ``_detect_and_resolve`` the import uses, the
    provider shown in the preview is the provider the import will use - there is
    no second provider-selection path to drift out of sync.
    """
    provider_id: str
    provider_name: str
    frame: pd.DataFrame                       # raw, un-normalized (provider output)
    raw: RawDataset
    detection: DetectionReport | None = None
    template_used: str | None = None


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
    detection: DetectionReport | None = None      # how the provider was recognized


class ImportService:
    def __init__(self, cache: CacheManager, templates: TemplateRepository,
                 pipeline: DataPipeline | None = None,
                 validator: ValidationEngine | None = None,
                 intelligence: ProviderIntelligence | None = None,
                 custom_providers: CustomProviderRepository | None = None) -> None:
        # Collaborators are injected by the bootstrap; the `or` fallbacks keep
        # the historical signature working for direct construction in tests.
        self._cache = cache
        self._templates = templates
        self._pipeline = pipeline or DataPipeline()
        self._validator = validator or ValidationEngine()
        self._intelligence = intelligence or ProviderIntelligence()
        self._customs = custom_providers

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

    def detect_provider(self, data: bytes, filename: str) -> DetectionReport:
        """Recognize the provider from the file's content, not just its name.

        Combines every signal the signatures declare - name, workbook metadata,
        sheet names, JSON shape, columns, fingerprints - into a weighted score.
        Saved club exports are scored alongside the built-in vendors.
        """
        intelligence = self._intelligence
        if self._customs is not None:
            extra = self._customs.signatures()
            if extra:
                intelligence = ProviderIntelligence(extra_signatures=extra)
        return intelligence.detect(data, filename)

    def _detect_and_resolve(self, data: bytes, filename: str,
                            provider_id: str | None) -> tuple[DataProvider, str, DetectionReport | None]:
        """The one provider-resolution path. Every consumer - import_file,
        inspect, the wizard, Open Play's preview - resolves a provider here and
        nowhere else, so the file is never recognized two different ways."""
        if provider_id:
            return self.pick_provider(filename, provider_id), provider_id, None
        detection = self.detect_provider(data, filename)
        provider, reported_id = self._resolve_provider(detection, filename)
        return provider, reported_id, detection

    def inspect(self, data: bytes, filename: str, *, provider_id: str | None = None,
                options: dict[str, Any] | None = None) -> FilePreview:
        """Resolve the provider and load the raw frame - the work ``import_file``
        does before it normalizes. Lets a caller see the provider decision and
        the raw columns (for a mapping preview) using the exact provider the
        import will use, without running or duplicating the pipeline."""
        provider, reported_id, detection = self._detect_and_resolve(data, filename, provider_id)
        raw = provider.load(BytesIO(data), filename, options=options)
        _detected, template_used = self.detect(raw.frame)
        return FilePreview(provider_id=reported_id, provider_name=provider.info.name,
                           frame=raw.frame, raw=raw, detection=detection,
                           template_used=template_used)

    def _resolve_provider(self, report: DetectionReport,
                          filename: str) -> tuple[DataProvider, str]:
        """Detected provider, else the historical filename-based choice.

        The fallback is what keeps every pre-intelligence import identical: a
        file no signature recognizes is picked exactly as it was before.
        """
        best = report.best
        if best is not None and not best.generic:
            if best.provider_id.startswith(CUSTOM_PREFIX):
                spec = self._customs.get(best.provider_id) if self._customs else None
                if spec is not None:
                    return provider_registry.create(spec.base_provider_id), spec.id
            elif best.provider_id in provider_registry:
                return provider_registry.create(best.provider_id), best.provider_id
        provider = self.pick_provider(filename)
        return provider, provider.info.id

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
        provider, reported_id, detection = self._detect_and_resolve(data, filename, provider_id)
        cache_key = self._cache_key(data, reported_id, mapping, coord_system,
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

        # what the file actually supplied vs what the schema filled in, so the
        # UI can tell the user which fields are real and which are placeholders
        provided = set(schema.apply_mapping(schema.clean_columns(raw.frame), final_mapping).columns)
        generated = [c for c in schema.CANONICAL if c in frame.columns and c not in provided]
        missing_required = [c for c in schema.REQUIRED if c not in provided]

        best = detection.best if detection else None
        event_schema = [str(e) for e in frame["event_type"].replace("", pd.NA)
                        .dropna().value_counts().head(12).index]

        result = ImportResult(
            frame=frame, provider_id=reported_id,
            mapping=final_mapping, mapping_confidence=detected.overall_confidence,
            coord_system=system, coord_confidence=conf,
            validation=validation, quality=quality, cleaning_log=cleaning_log,
            template_used=template_used, detection=detection,
            summary={
                "provider": reported_id,
                "provider_name": best.provider_name if best else provider.info.name,
                "provider_confidence": round(best.confidence, 3) if best else None,
                "provider_version": (best.schema_version if best and best.schema_version
                                     else getattr(provider.signature, "schema_version", "")),
                "provider_reasoning": detection.reasoning if detection else "explicitly selected",
                "matched_rules": [str(e) for e in best.matched_rules] if best else [],
                "failed_rules": [str(e) for e in best.failed_rules] if best else [],
                "ambiguous": bool(detection.ambiguous) if detection else False,
                "unknown_schema": bool(detection.unknown_schema) if detection else False,
                "alternatives": [f"{m.provider_name} ({m.confidence:.0%})"
                                 for m in (detection.candidates[1:4] if detection else [])],
                "mapping_confidence": round(detected.overall_confidence, 3),
                "generated_fields": generated,
                "missing_required": missing_required,
                "unknown_fields": list(detected.unmapped_sources),
                "warnings": [str(i) for i in getattr(validation, "issues", [])][:12],
                "event_schema": event_schema,
                "template_used": template_used,
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
