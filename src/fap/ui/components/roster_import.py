"""Shared roster bulk-import component (CSV / Excel).

A single, reusable Streamlit workspace that lets an analyst upload a spreadsheet
(``.csv`` / ``.xlsx`` / ``.xls``) and create many players at once. It is domain
neutral: the caller supplies a list of :class:`FieldSpec` describing the target
fields and a ``create_row`` callback that persists one coerced row. The same
component therefore drives both the First-Team squad import and the Scouting
registry import - no duplicate parsing/mapping/preview logic.

Design: the parsing + auto-mapping + coercion is pure (no Streamlit, easily
tested); only :func:`render_roster_import` touches the UI/session state. The
component never persists anything itself - every row is created through the
caller's callback, which reuses the existing service (capability-gated upstream).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Callable, Sequence


# --------------------------------------------------------------------------- spec
@dataclass(frozen=True)
class FieldSpec:
    """One importable target field.

    ``kind`` drives coercion: ``str`` | ``int`` | ``float`` | ``bool`` | ``list``
    (comma/semicolon separated). ``aliases`` are extra header names matched during
    auto-mapping (in addition to ``key`` and ``label``). ``choices`` restrict the
    accepted values (case-insensitive) for enumerated columns.
    """
    key: str
    label: str
    aliases: tuple[str, ...] = ()
    kind: str = "str"
    required: bool = False
    choices: tuple[str, ...] = ()
    help: str = ""


# ----------------------------------------------------------------------- parsing
def _norm(header: Any) -> str:
    """Normalise a header/alias for tolerant matching: lowercase, alphanumerics
    only (``"Shirt No."`` and ``"shirt_no"`` collapse to the same token)."""
    return re.sub(r"[^a-z0-9]", "", str(header).strip().lower())


def excel_sheets(data: bytes) -> list[str]:
    """Sheet names in an uploaded workbook (empty list when it is not an Excel
    file or cannot be opened)."""
    try:
        import pandas as pd
        return list(pd.ExcelFile(BytesIO(data)).sheet_names)
    except Exception:
        return []


def read_table(data: bytes, filename: str, *, sheet: Any = 0, header_row: int = 0):
    """Read an uploaded CSV/Excel byte payload into a DataFrame with string
    column names. Raises ``ValueError`` with a friendly message on failure."""
    import pandas as pd
    name = (filename or "").lower()
    try:
        if name.endswith((".xlsx", ".xls")):
            frame = pd.read_excel(BytesIO(data), sheet_name=sheet, header=header_row)
        else:
            frame = pd.read_csv(BytesIO(data), header=header_row,
                                sep=None, engine="python")
    except Exception as exc:                                   # pragma: no cover - message path
        raise ValueError(f"Could not read {filename!r}: {exc}") from exc
    frame.columns = [str(c).strip() for c in frame.columns]
    return frame


def auto_map(headers: Sequence[str], specs: Sequence[FieldSpec]) -> dict[str, str]:
    """Best-effort field -> header mapping by normalised key/label/alias match.
    A header is used at most once; the first spec to claim it wins."""
    by_norm: dict[str, str] = {}
    for h in headers:
        by_norm.setdefault(_norm(h), h)
    used: set[str] = set()
    mapping: dict[str, str] = {}
    for spec in specs:
        candidates = (spec.key, spec.label, *spec.aliases)
        for cand in candidates:
            h = by_norm.get(_norm(cand))
            if h is not None and h not in used:
                mapping[spec.key] = h
                used.add(h)
                break
    return mapping


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        import pandas as pd
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip() == ""


def coerce(value: Any, spec: FieldSpec) -> tuple[Any, str | None]:
    """Coerce one raw cell to the spec's kind. Returns ``(value, error)`` - a
    blank cell yields ``(None, None)`` so the field is simply omitted."""
    if _is_blank(value):
        return None, None
    raw = str(value).strip()
    kind = spec.kind
    try:
        if kind == "int":
            return int(float(raw.replace(",", ""))), None
        if kind == "float":
            return float(raw.replace(",", "")), None
        if kind == "bool":
            return raw.lower() in ("1", "true", "yes", "y", "t"), None
        if kind == "list":
            parts = [p.strip() for p in re.split(r"[;,/]", raw) if p.strip()]
            return parts, None
        # str
        if spec.choices:
            match = next((c for c in spec.choices if c.lower() == raw.lower()), None)
            if match is None:
                return None, (f"{spec.label}: {raw!r} is not one of "
                              f"{', '.join(spec.choices)}")
            return match, None
        return raw, None
    except Exception:
        return None, f"{spec.label}: cannot read {raw!r} as {kind}"


def build_rows(frame, specs: Sequence[FieldSpec],
               mapping: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn a DataFrame + field->header mapping into coerced row dicts. Fully
    blank rows are skipped; rows missing a required field or with a bad value are
    reported (1-based, matching a spreadsheet's data rows) and skipped."""
    by_key = {s.key: s for s in specs}
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    records = frame.to_dict(orient="records")
    for i, rec in enumerate(records, start=1):
        if all(_is_blank(rec.get(h)) for h in mapping.values()):
            continue
        row: dict[str, Any] = {}
        row_errors: list[str] = []
        for key, header in mapping.items():
            spec = by_key.get(key)
            if spec is None:
                continue
            val, err = coerce(rec.get(header), spec)
            if err:
                row_errors.append(err)
            elif val is not None and val != []:
                row[key] = val
        missing = [s.label for s in specs
                   if s.required and s.key not in row]
        if missing:
            row_errors.append("missing " + ", ".join(missing))
        if row_errors:
            issues.append(f"Row {i}: " + "; ".join(row_errors))
            continue
        rows.append(row)
    return rows, issues


# ------------------------------------------------------------------------ render
def render_roster_import(*, key: str, specs: Sequence[FieldSpec],
                         create_row: Callable[[dict[str, Any]], Any],
                         noun: str = "player", can_edit: bool = True) -> int:
    """Render the upload -> map -> preview -> import workspace.

    ``create_row`` is called once per validated row with the coerced ``dict`` and
    must persist it (raising on failure). Returns the number of records created
    on the run the import button is pressed, else ``0``.
    """
    import streamlit as st

    from fap.theme import components as C

    if not can_edit:
        C.render_alert(f"You do not have permission to add {noun}s.", "warning")
        return 0

    up = st.file_uploader(
        "Spreadsheet", type=["csv", "xlsx", "xls"], key=f"{key}_file",
        help="A CSV or Excel file with one row per player. The first row must be "
             "the column headers.")
    if up is None:
        _template_hint(specs, noun)
        return 0

    data = up.getvalue()
    is_excel = up.name.lower().endswith((".xlsx", ".xls"))
    opt = st.columns(2)
    sheet: Any = 0
    if is_excel:
        sheets = excel_sheets(data)
        if sheets:
            sheet = opt[0].selectbox("Sheet", sheets, key=f"{key}_sheet")
    header_row = int(opt[1].number_input(
        "Header row", 1, 20, 1, key=f"{key}_hdr",
        help="Which row holds the column names (1 = first row).")) - 1

    try:
        frame = read_table(data, up.name, sheet=sheet, header_row=header_row)
    except ValueError as exc:
        C.render_alert(str(exc), "danger")
        return 0
    if frame.empty:
        C.render_alert("The file has no data rows.", "warning")
        return 0

    headers = [str(c) for c in frame.columns]
    st.caption(f"{len(frame)} row(s) · {len(headers)} column(s) detected")

    # ---- column mapping (auto-detected, user-overridable) ----
    auto = auto_map(headers, specs)
    st.markdown("**Map columns**  ·  matched automatically where possible")
    mapping: dict[str, str] = {}
    cols = st.columns(3)
    options = ["— skip —", *headers]
    for i, spec in enumerate(specs):
        default = auto.get(spec.key)
        idx = options.index(default) if default in options else 0
        label = spec.label + (" *" if spec.required else "")
        choice = cols[i % 3].selectbox(label, options, index=idx,
                                       key=f"{key}_map_{spec.key}", help=spec.help)
        if choice != "— skip —":
            mapping[spec.key] = choice

    missing_req = [s.label for s in specs if s.required and s.key not in mapping]
    if missing_req:
        C.render_alert("Map the required field(s): " + ", ".join(missing_req),
                       "warning")
        return 0

    rows, issues = build_rows(frame, specs, mapping)

    # ---- preview ----
    st.markdown("**Preview**")
    if rows:
        preview = [{s.label: _display(r.get(s.key)) for s in specs if s.key in mapping}
                   for r in rows[:25]]
        st.dataframe(preview, use_container_width=True, hide_index=True)
    else:
        st.caption("No importable rows yet.")
    st.caption(f"{len(rows)} ready to import" +
               (f" · {len(issues)} row(s) skipped" if issues else ""))
    if issues:
        with st.expander(f"{len(issues)} row(s) skipped — details"):
            for msg in issues[:200]:
                st.write("• " + msg)

    # ---- import ----
    if not rows:
        return 0
    if not st.button(f"Import {len(rows)} {noun}(s)", type="primary",
                     key=f"{key}_go", use_container_width=True):
        return 0
    created = 0
    failures: list[str] = []
    progress = st.progress(0.0)
    for n, row in enumerate(rows, start=1):
        try:
            create_row(dict(row))
            created += 1
        except Exception as exc:                              # per-row isolation
            label = row.get("name") or row.get("display_name") or f"row {n}"
            failures.append(f"{label}: {exc}")
        progress.progress(n / len(rows))
    progress.empty()
    if created:
        C.render_alert(f"Imported {created} {noun}(s).", "success")
    if failures:
        with st.expander(f"{len(failures)} {noun}(s) failed"):
            for msg in failures[:200]:
                st.write("• " + msg)
    return created


def _display(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value)


def _template_hint(specs: Sequence[FieldSpec], noun: str) -> None:
    import streamlit as st
    required = [s.label for s in specs if s.required]
    optional = [s.label for s in specs if not s.required]
    st.caption(
        f"Upload a CSV or Excel file with one {noun} per row. "
        + (f"Required column: **{', '.join(required)}**. " if required else "")
        + "Recognised columns: " + ", ".join(optional[:20])
        + ("…" if len(optional) > 20 else "")
        + ". Column names are matched automatically — you can adjust the mapping "
          "after uploading.")
