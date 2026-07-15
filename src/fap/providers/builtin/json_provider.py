"""Generic JSON provider - the catch-all for any JSON events export whose
shape is not known in advance.

Vendor JSON feeds (StatsBomb, Wyscout, SkillCorner, Second Spectrum) keep their
own providers and still win: ImportService.pick_provider sorts category="file"
catch-alls last, so this provider only sees files no vendor plugin claims.

Makes no assumption about field names - it locates the record array, flattens
nested objects into ``parent_child`` columns and hands every field through
untouched. The pipeline does the mapping and normalizing, as always.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, BinaryIO

import pandas as pd

from fap.core.exceptions import ProviderError
from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry
from fap.providers.detection import detect_format
from fap.providers.signature import ProviderSignature

_MAX_SEARCH_DEPTH = 3


def _parse(data: bytes, encoding: str, filename: str) -> Any:
    """Whole-document JSON, falling back to JSON Lines (one object per line)."""
    text = data.decode(encoding, errors="replace").strip()
    if not text:
        raise ProviderError(f"Could not parse JSON {filename!r}: file is empty.")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    records: list[Any] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"Could not parse JSON {filename!r}: invalid JSON on line {lineno}: {exc.msg}"
            ) from exc
    if not records:
        raise ProviderError(f"Could not parse JSON {filename!r}: no JSON value found.")
    return records


def _is_record_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(i, dict) for i in value)


def _find_record_list(node: dict[str, Any], prefix: str, depth: int) -> tuple[list[Any] | None, str | None]:
    """Longest list-of-objects anywhere in a dict root wins - that is the event
    array. Nested dicts are searched to a bounded depth so wrapper envelopes
    like {"match": {"events": [...]}} resolve without unbounded recursion."""
    if depth > _MAX_SEARCH_DEPTH:
        return None, None
    best: list[Any] | None = None
    best_path: str | None = None
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if _is_record_list(value):
            if best is None or len(value) > len(best):
                best, best_path = value, path
        elif isinstance(value, dict):
            nested, nested_path = _find_record_list(value, path, depth + 1)
            if nested is not None and (best is None or len(nested) > len(best)):
                best, best_path = nested, nested_path
    return best, best_path


def _at_path(payload: Any, path: str) -> list[Any]:
    """Explicit ``record_path`` override from the import options, e.g. "match.events"."""
    node: Any = payload
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ProviderError(f"record_path {path!r} not found in the JSON document.")
        node = node[part]
    if isinstance(node, dict):
        return [node]
    if not isinstance(node, list):
        raise ProviderError(f"record_path {path!r} does not point at a list of objects.")
    return node


def _records_from(payload: Any, filename: str) -> tuple[list[Any], str | None]:
    """Supported roots: a list of objects, a dict wrapping an event array,
    a dict whose values are the records, and a single object (one row)."""
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, dict):
        found, path = _find_record_list(payload, "", 0)
        if found is not None:
            return found, path
        if payload and all(isinstance(v, dict) for v in payload.values()):
            return list(payload.values()), None
        return [payload], None
    raise ProviderError(
        f"Could not parse JSON {filename!r}: expected an object or a list of objects, "
        f"got {type(payload).__name__}."
    )


@provider_registry.register
class JsonProvider(DataProvider):
    info = PluginInfo(
        id="generic_json", name="JSON / custom events export", category="file",
        description="Any JSON: list of objects, nested event array or dictionary root; "
                    "JSON Lines supported and nested fields flattened automatically.",
    )
    signature = ProviderSignature(
        supported_extensions=(".json", ".jsonl", ".ndjson"),
        generic=True, priority=-100, schema_version="generic",
    )

    def supports(self, filename: str) -> bool:
        return filename.lower().endswith((".json", ".jsonl", ".ndjson"))

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        options = options or {}
        data = source.read()
        fmt = detect_format(data, filename)
        payload = _parse(data, options.get("encoding", fmt.encoding), filename)

        record_path = options.get("record_path")
        if record_path:
            records, path = _at_path(payload, record_path), record_path
        else:
            records, path = _records_from(payload, filename)

        if not records:
            raise ProviderError(f"Could not parse JSON {filename!r}: no records found.")
        if not all(isinstance(r, dict) for r in records):
            raise ProviderError(
                f"Could not parse JSON {filename!r}: expected objects, found bare values "
                f"(use the record_path option to point at the event array)."
            )
        try:
            frame = pd.json_normalize(records, sep="_", max_level=options.get("max_level"))
        except Exception as exc:
            raise ProviderError(f"Could not parse JSON {filename!r}: {exc}") from exc

        return RawDataset(frame=frame, meta={"format": asdict(fmt), "record_path": path,
                                             "records": int(len(frame))})
