"""Smart Import Wizard.

Step 1  Choose data source (provider plugin, auto-detect available)
Step 2  Preview dataset + automatic format detection (delimiter/encoding/sheets/header)
Step 3  Column mapping - auto-detected, manual override when confidence is low,
        save/reuse mapping templates
Step 4  Coordinate system - auto-detected, override possible
Step 5  Run pipeline with progress -> validation report, quality score, summary
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from fap.bootstrap import AppContext
from fap.core.exceptions import FAPError
from fap.pipeline.columns import CONFIDENCE_THRESHOLD, detect_columns
from fap.pipeline.coordinates import coord_registry, detect_coordinate_system
from fap.pipeline.schema import CANONICAL
from fap.providers.base import provider_registry
from fap.providers.detection import detect_format
from fap.state import keys
from fap.ui.components import app_header, kpi_card, note_box, section_title


def render(ctx: AppContext) -> None:
    app_header("Smart Import Wizard",
               "Import any football event dataset into the one canonical model.")

    step = ctx.state.get(keys.WIZARD_STEP) or 1
    st.progress((step - 1) / 4, text=f"Step {step} of 5")

    if step == 1:
        _step1_source(ctx)
    elif step == 2:
        _step2_preview(ctx)
    elif step == 3:
        _step3_mapping(ctx)
    elif step == 4:
        _step4_coordinates(ctx)
    else:
        _step5_import(ctx)


def _goto(ctx: AppContext, step: int) -> None:
    ctx.state.set(keys.WIZARD_STEP, step)
    st.rerun()


# ------------------------------------------------------------------ step 1
def _step1_source(ctx: AppContext) -> None:
    section_title("1) Choose data source")
    infos = ctx.providers.infos()
    labels = ["Auto-detect from file"] + [f"{i.name}" for i in infos]
    choice = st.selectbox("Data source", labels)
    provider_id = None if choice == labels[0] else infos[labels.index(choice) - 1].id
    if provider_id:
        st.caption(ctx.providers.get(provider_id).info.description)

    uploaded = st.file_uploader(
        "Upload event data",
        type=["csv", "tsv", "txt", "xlsx", "xls", "json", "jsonl", "xml"])
    if uploaded is not None:
        ctx.state.set(keys.WIZARD_FILE, {
            "name": uploaded.name, "data": uploaded.getvalue(), "provider_id": provider_id,
            "options": {},
        })
        _goto(ctx, 2)


# ------------------------------------------------------------------ step 2
def _step2_preview(ctx: AppContext) -> None:
    file: dict[str, Any] = ctx.state.get(keys.WIZARD_FILE) or {}
    if not file:
        _goto(ctx, 1)
        return
    section_title("2) Preview & format detection")

    fmt = detect_format(file["data"], file["name"])
    c1, c2, c3, c4 = st.columns(4)
    with c1: kpi_card("Format", fmt.kind.upper())
    with c2: kpi_card("Encoding", fmt.encoding)
    with c3: kpi_card("Delimiter", repr(fmt.delimiter) if fmt.kind == "csv" else "-")
    with c4: kpi_card("Header row", fmt.header_row if fmt.kind == "csv" else 0)

    options = dict(file.get("options", {}))
    if fmt.sheet_names:
        options["sheet"] = st.selectbox("Sheet", list(fmt.sheet_names))

    try:
        raw = _load_raw(ctx, file, options)
        st.caption(f"{len(raw.frame):,} rows x {len(raw.frame.columns)} columns")
        st.dataframe(raw.frame.head(25), width="stretch")
    except FAPError as exc:
        st.error(str(exc))
        if st.button("Back"):
            _goto(ctx, 1)
        return

    file["options"] = options
    ctx.state.set(keys.WIZARD_FILE, file)
    b1, b2 = st.columns(2)
    if b1.button("Back"):
        _goto(ctx, 1)
    if b2.button("Continue to column mapping", type="primary"):
        _goto(ctx, 3)


# ------------------------------------------------------------------ step 3
def _step3_mapping(ctx: AppContext) -> None:
    file: dict[str, Any] = ctx.state.get(keys.WIZARD_FILE) or {}
    if not file:
        _goto(ctx, 1)
        return
    section_title("3) Column mapping")

    raw = _load_raw(ctx, file, file.get("options"))
    detected, template_name = ctx.importer.detect(raw.frame)
    if template_name:
        st.success(f"Saved mapping template **{template_name}** matched this file "
                   f"and was applied automatically.")
    conf = detected.overall_confidence
    note_box(f"Auto-detection confidence: <b>{conf:.0%}</b>"
             + ("" if conf >= CONFIDENCE_THRESHOLD else
                " - please review the mapping below."))

    manual = st.toggle("Manual mapping", value=detected.needs_review and not template_name)
    mapping = dict(raw.column_mapping)
    mapping.update(detected.rename_dict())

    if manual:
        sources = ["(ignore)"] + [str(c) for c in raw.frame.columns]
        reverse = {v: k for k, v in mapping.items()}
        cols = st.columns(3)
        for i, canonical in enumerate(("x", "y", "end_x", "end_y", "event_type", "sub_event",
                                       "player", "team", "opponent", "outcome", "minute",
                                       "second", "period", "match_id", "jersey_number",
                                       "body_part", "play_pattern", "sequence_id")):
            current = reverse.get(canonical, "(ignore)")
            with cols[i % 3]:
                chosen = st.selectbox(canonical, sources,
                                      index=sources.index(current) if current in sources else 0,
                                      key=f"map::{canonical}")
            mapping = {s: c for s, c in mapping.items() if c != canonical}
            if chosen != "(ignore)":
                mapping[chosen] = canonical
    else:
        preview = pd.DataFrame(
            [{"source column": s, "canonical field": c,
              "confidence": f"{detected.confidence.get(c, 1.0):.0%}"}
             for s, c in mapping.items()])
        st.dataframe(preview, width="stretch", height=280)
        if detected.unmapped_sources:
            st.caption("Unmapped source columns (kept as extra data): "
                       + ", ".join(detected.unmapped_sources))

    save_as = st.text_input("Save this mapping as a template (optional)", "")
    file["mapping"] = mapping
    file["save_template_as"] = save_as.strip()
    ctx.state.set(keys.WIZARD_FILE, file)

    b1, b2 = st.columns(2)
    if b1.button("Back"):
        _goto(ctx, 2)
    if b2.button("Continue to coordinates", type="primary"):
        _goto(ctx, 4)


# ------------------------------------------------------------------ step 4
def _step4_coordinates(ctx: AppContext) -> None:
    file: dict[str, Any] = ctx.state.get(keys.WIZARD_FILE) or {}
    if not file:
        _goto(ctx, 1)
        return
    section_title("4) Coordinate system")

    raw = _load_raw(ctx, file, file.get("options"))
    mapped = raw.frame.rename(columns=file.get("mapping", {}))
    if raw.native_coord_system != "0-100":
        detected_id, conf = raw.native_coord_system, 1.0
        st.info(f"Provider declares its coordinate system: **{detected_id}**.")
    else:
        detected_id, conf = detect_coordinate_system(mapped)
        note_box(f"Detected coordinate system: <b>{detected_id}</b> "
                 f"(confidence {conf:.0%})")

    ids = coord_registry.ids()
    names = {i: coord_registry.get(i).info.name for i in ids}
    chosen = st.selectbox("Coordinate system", ids,
                          index=ids.index(detected_id) if detected_id in ids else 0,
                          format_func=lambda i: names[i])
    flip = st.checkbox("Team attacks right-to-left in this data (flip to left-to-right)")

    file["coord_system"], file["flip"] = chosen, flip
    ctx.state.set(keys.WIZARD_FILE, file)

    b1, b2 = st.columns(2)
    if b1.button("Back"):
        _goto(ctx, 3)
    if b2.button("Run import", type="primary"):
        _goto(ctx, 5)


# ------------------------------------------------------------------ step 5
def _step5_import(ctx: AppContext) -> None:
    file: dict[str, Any] = ctx.state.get(keys.WIZARD_FILE) or {}
    if not file:
        _goto(ctx, 1)
        return
    section_title("5) Import summary")

    progress = st.progress(0, text="Loading provider...")
    try:
        progress.progress(20, text="Parsing, mapping and normalizing...")
        result = ctx.importer.import_file(
            file["data"], file["name"], provider_id=file.get("provider_id"),
            mapping=file.get("mapping"), coord_system=file.get("coord_system"),
            flip_direction=bool(file.get("flip")), options=file.get("options"),
        )
        progress.progress(80, text="Validating and scoring...")
        if file.get("save_template_as"):
            raw = _load_raw(ctx, file, file.get("options"))
            ctx.importer.save_template(file["save_template_as"], result.provider_id,
                                       [str(c) for c in raw.frame.columns], result.mapping)
        progress.progress(100, text="Done")
    except FAPError as exc:
        progress.empty()
        st.error(f"Import failed: {exc}")
        if st.button("Back"):
            _goto(ctx, 4)
        return

    ctx.state.set(keys.IMPORT_RESULT, result)
    ctx.state.set(keys.CANONICAL_DATASET, result.frame)

    if result.cache_hit:
        st.info("Loaded instantly from the normalized-dataset cache.")
    c = st.columns(5)
    with c[0]: kpi_card("Rows", f"{result.summary['rows']:,}")
    with c[1]: kpi_card("Matches", result.summary["matches"])
    with c[2]: kpi_card("Teams", result.summary["teams"])
    with c[3]: kpi_card("Players", result.summary["players"])
    with c[4]: kpi_card("Quality", f"{result.quality.overall:.0f}/100")

    section_title("Data quality")
    note_box(f"Overall <b>{result.quality.overall:.0f}/100 - {result.quality.grade}</b>")
    qcols = st.columns(len(result.quality.components))
    for col, (name, value) in zip(qcols, result.quality.components.items()):
        with col:
            kpi_card(name.replace("_", " ").title(), f"{value:.0f}")

    section_title("Validation report")
    st.markdown(result.validation.to_markdown())
    with st.expander("Cleaning actions"):
        for action in result.cleaning_log:
            st.markdown(f"- {action}")
    with st.expander("Canonical dataset preview"):
        st.dataframe(result.frame.head(50), width="stretch")

    st.success("Dataset is normalized and ready. Every future visualization will "
               "consume this canonical model.")
    if st.button("Import another file"):
        ctx.state.delete(keys.WIZARD_FILE)
        _goto(ctx, 1)


# ------------------------------------------------------------------ shared
def _load_raw(ctx: AppContext, file: dict[str, Any], options: dict | None):
    from io import BytesIO
    provider = ctx.importer.pick_provider(file["name"], file.get("provider_id"))
    return provider.load(BytesIO(file["data"]), file["name"], options=options)
