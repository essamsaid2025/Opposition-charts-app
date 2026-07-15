"""Provider Intelligence: recognize a football data provider from evidence.

The engine knows nothing about any particular vendor. It takes one bounded
FileSample and scores every registered signature against it with the same
rules, so adding a provider is one class + one registration and this file never
changes. There is no ``if provider == ...`` anywhere, by construction.

Design rules that matter:

* No single signal decides. A filename is 10 points; a fingerprint is 40; a
  missing required column is -25. A vendor wins by accumulating agreement.
* Generic catch-alls are never *preferred*. They carry `generic=True` and are
  only reported when nothing else earned any evidence, which preserves the
  legacy ordering (vendor plugins outrank the file catch-alls).
* Evidence is reported, not just consumed: every match carries the rules that
  fired, the rules that failed, and a sentence a human can read.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from fap.core.naming import normalize_name
from fap.core.plugin import PluginRegistry
from fap.providers.base import DataProvider, provider_registry
from fap.providers.sampling import FileSample, sample_file
from fap.providers.signature import (
    PENALTY_MISSING_REQUIRED, PENALTY_UNKNOWN_SCHEMA, ProviderSignature,
    WEIGHT_FILENAME, WEIGHT_FINGERPRINT, WEIGHT_JSON_STRUCTURE, WEIGHT_METADATA,
    WEIGHT_OPTIONAL_COLUMNS, WEIGHT_REQUIRED_COLUMNS, WEIGHT_SHEET_NAMES,
    WEIGHT_VALUE_PATTERNS,
)

logger = logging.getLogger(__name__)

#: A provider must earn at least this to be chosen over the legacy fallback.
MIN_SCORE = 1
#: Below this, the caller should ask the user rather than assume.
CONFIDENT = 0.5
#: Two candidates this close together are ambiguous.
AMBIGUITY_MARGIN = 0.15


@dataclass(frozen=True, slots=True)
class Evidence:
    rule: str
    points: int
    detail: str

    def __str__(self) -> str:
        return f"{self.rule} ({self.points:+d}): {self.detail}"


@dataclass(frozen=True, slots=True)
class ProviderMatch:
    provider_id: str
    provider_name: str
    score: int
    confidence: float                       # 0..1, normalized by what it could earn
    matched_rules: tuple[Evidence, ...] = ()
    failed_rules: tuple[Evidence, ...] = ()
    schema_version: str = ""
    generic: bool = False

    @property
    def strong(self) -> bool:
        """Did anything beyond incidental column overlap fire?

        Typical-column agreement is the one signal weak enough to appear by
        chance - plenty of exports have an `x` column. It can support a match
        but must never carry one on its own.
        """
        return any(e.rule != "optional_columns" for e in self.matched_rules)

    @property
    def reasoning(self) -> str:
        if not self.matched_rules:
            return f"{self.provider_name}: no positive evidence"
        drivers = ", ".join(e.detail for e in self.matched_rules[:3])
        text = f"{self.provider_name} at {self.confidence:.0%} confidence from {drivers}"
        if self.failed_rules:
            text += f"; against it: {self.failed_rules[0].detail}"
        return text


@dataclass(frozen=True, slots=True)
class DetectionReport:
    sample: FileSample
    candidates: tuple[ProviderMatch, ...] = ()
    unknown_schema: bool = False

    @property
    def best(self) -> ProviderMatch | None:
        return self.candidates[0] if self.candidates else None

    @property
    def confident(self) -> bool:
        return bool(self.best) and self.best.confidence >= CONFIDENT

    @property
    def ambiguous(self) -> bool:
        """Two providers explaining the file about equally well."""
        if len(self.candidates) < 2:
            return False
        first, second = self.candidates[0], self.candidates[1]
        if second.generic or second.score <= 0:
            return False
        return (first.confidence - second.confidence) < AMBIGUITY_MARGIN

    @property
    def reasoning(self) -> str:
        return self.best.reasoning if self.best else "no provider recognized this file"


def _norm_all(names: Iterable[str]) -> set[str]:
    return {normalize_name(n) for n in names if str(n).strip()}


class ProviderIntelligence:
    """Scores every signature against one sample. Stateless and reusable."""

    def __init__(self, registry: PluginRegistry[DataProvider] | None = None,
                 extra_signatures: Sequence[tuple[str, str, ProviderSignature]] = ()) -> None:
        self._registry = registry if registry is not None else provider_registry
        # (provider_id, display name, signature) for providers that are not plugins,
        # e.g. custom club exports loaded from the database.
        self._extra = tuple(extra_signatures)

    # ------------------------------------------------------------ public
    def detect(self, data: bytes, filename: str) -> DetectionReport:
        return self.detect_sample(sample_file(data, filename))

    def detect_sample(self, sample: FileSample) -> DetectionReport:
        matches: list[ProviderMatch] = []
        for provider_id, name, signature in self._signatures():
            match = self._score(provider_id, name, signature, sample)
            if match is not None:
                matches.append(match)
        # highest score wins; priority only breaks ties; generics sink to the end
        matches.sort(key=lambda m: (not m.generic, m.score, m.confidence), reverse=True)
        ranked = tuple(m for m in matches
                       if m.score >= MIN_SCORE and not m.generic and m.strong)
        if not ranked:
            # nothing recognized it: report the generic candidates, unknown schema
            generics = tuple(m for m in matches if m.generic)
            return DetectionReport(sample=sample, candidates=generics, unknown_schema=True)
        return DetectionReport(sample=sample, candidates=ranked, unknown_schema=False)

    # ------------------------------------------------------------ internals
    def _signatures(self) -> list[tuple[str, str, ProviderSignature]]:
        out: list[tuple[str, str, ProviderSignature]] = []
        for cls in self._registry:
            signature = getattr(cls, "signature", None)
            if isinstance(signature, ProviderSignature):
                out.append((cls.info.id, cls.info.name, signature))
        out.extend(self._extra)
        return out

    @staticmethod
    def _extension_allows(signature: ProviderSignature, sample: FileSample) -> bool:
        if not signature.supported_extensions:
            return True
        return sample.extension in signature.supported_extensions

    def _score(self, provider_id: str, name: str, signature: ProviderSignature,
               sample: FileSample) -> ProviderMatch | None:
        # extension is a gate, not evidence: a provider that cannot read the
        # bytes is not a candidate at any confidence
        if not self._extension_allows(signature, sample):
            return None

        matched: list[Evidence] = []
        failed: list[Evidence] = []
        score = 0
        # Fingerprints look at CONTENT only. If they also read the filename, a
        # single signal (the name) would fire two rules and fake agreement.
        content = "\n".join((sample.text_head, sample.metadata, " ".join(sample.columns),
                             " ".join(sample.sheet_names))).lower()
        columns = _norm_all(sample.columns)

        low_name = sample.filename.lower()
        hits = [p for p in signature.filename_patterns if p.lower() in low_name]
        if hits:
            score += WEIGHT_FILENAME
            matched.append(Evidence("filename", WEIGHT_FILENAME, f"name contains {hits[0]!r}"))

        meta = f"{sample.metadata}".lower()
        hits = [p for p in signature.metadata_patterns if p.lower() in meta]
        if hits:
            score += WEIGHT_METADATA
            matched.append(Evidence("metadata", WEIGHT_METADATA,
                                    f"workbook metadata mentions {hits[0]!r}"))

        sheets = _norm_all(sample.sheet_names)
        hits = [s for s in signature.sheet_names if normalize_name(s) in sheets]
        if hits:
            score += WEIGHT_SHEET_NAMES
            matched.append(Evidence("sheet_names", WEIGHT_SHEET_NAMES,
                                    f"sheet {hits[0]!r} present"))

        if signature.required_columns:
            need = {normalize_name(c) for c in signature.required_columns}
            missing = need - columns
            if not missing:
                score += WEIGHT_REQUIRED_COLUMNS
                matched.append(Evidence("required_columns", WEIGHT_REQUIRED_COLUMNS,
                                        f"all {len(need)} required columns present"))
            else:
                score += PENALTY_MISSING_REQUIRED
                failed.append(Evidence("required_columns", PENALTY_MISSING_REQUIRED,
                                       f"missing {sorted(missing)[0]!r}"))

        if signature.optional_columns:
            present = [c for c in signature.optional_columns if normalize_name(c) in columns]
            if present:
                earned = max(1, round(WEIGHT_OPTIONAL_COLUMNS * len(present)
                                      / len(signature.optional_columns)))
                score += earned
                matched.append(Evidence("optional_columns", earned,
                                        f"{len(present)} typical columns present"))

        keys = _norm_all(sample.json_keys)
        hits = [k for k in signature.json_patterns if normalize_name(k) in keys]
        if hits:
            score += WEIGHT_JSON_STRUCTURE
            matched.append(Evidence("json_structure", WEIGHT_JSON_STRUCTURE,
                                    f"top-level key {hits[0]!r}"))

        hits = [p for p in signature.nested_object_patterns if sample.has_nested_path(p)]
        if hits:
            score += WEIGHT_JSON_STRUCTURE
            matched.append(Evidence("nested_objects", WEIGHT_JSON_STRUCTURE,
                                    f"nested {hits[0]!r}"))

        hits = [i for i in signature.provider_identifiers if i.lower() in content]
        if hits:
            score += WEIGHT_FINGERPRINT
            matched.append(Evidence("fingerprint", WEIGHT_FINGERPRINT,
                                    f"identifier {hits[0]!r} in the data"))

        structural = bool(signature.required_columns or signature.json_patterns
                          or signature.nested_object_patterns)
        if structural and not columns and not sample.json_keys:
            score += PENALTY_UNKNOWN_SCHEMA
            failed.append(Evidence("unknown_schema", PENALTY_UNKNOWN_SCHEMA,
                                   "file structure could not be sampled"))

        if signature.known_value_patterns:
            blob = "\n".join(sample.values[:100])
            for pattern in signature.known_value_patterns:
                try:
                    if re.search(pattern, blob):
                        score += WEIGHT_VALUE_PATTERNS
                        matched.append(Evidence("value_patterns", WEIGHT_VALUE_PATTERNS,
                                                f"values match {pattern!r}"))
                        break
                except re.error:                       # a bad signature must not break detection
                    logger.warning("provider %s has an invalid value pattern %r",
                                   provider_id, pattern)

        achievable = signature.achievable_score()
        if achievable <= 0:
            confidence = 0.0
        else:
            confidence = max(0.0, min(1.0, score / achievable))
        return ProviderMatch(provider_id=provider_id, provider_name=name, score=score,
                             confidence=confidence, matched_rules=tuple(matched),
                             failed_rules=tuple(failed),
                             schema_version=signature.schema_version,
                             generic=signature.generic)
