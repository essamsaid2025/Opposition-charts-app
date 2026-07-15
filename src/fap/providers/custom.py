"""Custom club exports: a provider the platform learns instead of ships.

When no vendor recognizes a file, the engine still knows a great deal about it
- its extension and its exact column shape. That is enough to build a
*temporary* provider on the spot: it reads through the matching generic reader,
and its signature is the file's own fingerprint. Nothing is persisted unless
the user saves it; once saved, the intelligence engine scores it alongside the
built-in vendors, so the next export of that shape is recognized on upload.

Reuses rather than reinvents: the generic readers do the parsing, and the id is
derived with pipeline.templates.column_signature - the same column fingerprint
the mapping templates key on.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from fap.core.naming import column_signature
from fap.db.engine import Database
from fap.providers.sampling import FileSample
from fap.providers.signature import ProviderSignature

CUSTOM_PREFIX = "custom::"

#: which generic reader parses a custom export of each kind
_BASE_BY_KIND = {"csv": "generic_csv", "excel": "generic_excel", "json": "generic_json"}

MAX_SIGNATURE_COLUMNS = 12


@dataclass(frozen=True, slots=True)
class CustomProviderSpec:
    id: str
    name: str
    base_provider_id: str
    signature: ProviderSignature

    @property
    def saved(self) -> bool:
        return not self.name.startswith("Unrecognized")


def base_provider_for(sample: FileSample) -> str | None:
    """The generic reader that can physically parse this file, if any."""
    return _BASE_BY_KIND.get(sample.kind)


def temporary_custom_provider(sample: FileSample) -> CustomProviderSpec | None:
    """Build an unsaved provider from the file's own shape.

    Returns None when no generic reader could parse the file at all - there is
    nothing to offer the user in that case.
    """
    base = base_provider_for(sample)
    if base is None or not sample.columns:
        return None
    columns = tuple(str(c) for c in sample.columns[:MAX_SIGNATURE_COLUMNS])
    return CustomProviderSpec(
        id=f"{CUSTOM_PREFIX}{column_signature(list(columns))}",
        name=f"Unrecognized export ({sample.filename})",
        base_provider_id=base,
        signature=ProviderSignature(
            supported_extensions=(sample.extension,) if sample.extension else (),
            required_columns=columns,
            schema_version="custom-v1",
            priority=50,          # a club's own export beats a generic guess
        ),
    )


class CustomProviderRepository:
    """Saved club exports. Same shape as TemplateRepository, same Database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, spec: CustomProviderSpec, name: str) -> CustomProviderSpec:
        saved = CustomProviderSpec(id=spec.id, name=name,
                                   base_provider_id=spec.base_provider_id,
                                   signature=spec.signature)
        self._db.execute(
            "INSERT OR REPLACE INTO custom_providers (id, name, base_provider_id, signature)"
            " VALUES (?, ?, ?, ?)",
            (saved.id, saved.name, saved.base_provider_id, json.dumps(asdict(saved.signature))),
        )
        return saved

    def get(self, spec_id: str) -> CustomProviderSpec | None:
        rows = self._db.query("SELECT * FROM custom_providers WHERE id = ?", (spec_id,))
        return self._row(rows[0]) if rows else None

    def list_all(self) -> list[CustomProviderSpec]:
        return [self._row(r) for r in
                self._db.query("SELECT * FROM custom_providers ORDER BY created_at DESC")]

    def delete(self, spec_id: str) -> None:
        self._db.execute("DELETE FROM custom_providers WHERE id = ?", (spec_id,))

    def signatures(self) -> list[tuple[str, str, ProviderSignature]]:
        """Feed for ProviderIntelligence(extra_signatures=...)."""
        return [(s.id, s.name, s.signature) for s in self.list_all()]

    @staticmethod
    def _row(row) -> CustomProviderSpec:
        payload = json.loads(row["signature"])
        payload = {k: (tuple(v) if isinstance(v, list) else v) for k, v in payload.items()}
        return CustomProviderSpec(id=row["id"], name=row["name"],
                                  base_provider_id=row["base_provider_id"],
                                  signature=ProviderSignature(**payload))
