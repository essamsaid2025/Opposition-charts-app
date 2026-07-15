"""Mapping templates: a saved column mapping keyed by a *signature* of the
source columns. When the same file shape is imported again, the template is
found and applied automatically."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from fap.core.naming import column_signature   # re-exported: the one fingerprint
from fap.db.engine import Database


@dataclass(frozen=True, slots=True)
class MappingTemplate:
    id: str
    name: str
    provider_id: str
    signature: str
    mapping: dict[str, str]           # source column -> canonical field


class TemplateRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, name: str, provider_id: str, columns: list[str],
             mapping: dict[str, str]) -> MappingTemplate:
        template = MappingTemplate(id=str(uuid.uuid4()), name=name, provider_id=provider_id,
                                   signature=column_signature(columns), mapping=dict(mapping))
        self._db.execute(
            "INSERT INTO mapping_templates (id, name, provider_id, signature, mapping)"
            " VALUES (?, ?, ?, ?, ?)",
            (template.id, template.name, template.provider_id, template.signature,
             json.dumps(template.mapping)),
        )
        return template

    def find_by_signature(self, columns: list[str]) -> MappingTemplate | None:
        rows = self._db.query(
            "SELECT * FROM mapping_templates WHERE signature = ? ORDER BY created_at DESC LIMIT 1",
            (column_signature(columns),),
        )
        return self._row(rows[0]) if rows else None

    def list_all(self) -> list[MappingTemplate]:
        return [self._row(r) for r in self._db.query(
            "SELECT * FROM mapping_templates ORDER BY created_at DESC")]

    def delete(self, template_id: str) -> None:
        self._db.execute("DELETE FROM mapping_templates WHERE id = ?", (template_id,))

    @staticmethod
    def _row(row) -> MappingTemplate:
        return MappingTemplate(id=row["id"], name=row["name"], provider_id=row["provider_id"],
                               signature=row["signature"], mapping=json.loads(row["mapping"]))
