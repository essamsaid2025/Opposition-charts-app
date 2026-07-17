"""Report Editor - the visual document editor.

Left: report structure · Center: document preview · Right: properties.

Every change is written straight to the platform database through
ReportsManager (autosave); nothing about the report lives in session_state -
only *which* report is open (navigation). Charts are stored as references and
regenerated from the saved dataset; images are referenced by id.
"""
from __future__ import annotations

import base64

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.reports import (
    add_block, chart_block, delete_block, duplicate_block, image_block,
    move_block, set_hidden, text_block,
)
from fap.ui.page import Page, page_registry

OPEN_REPORT = "_open_report_id"        # navigation state only
SELECTED_BLOCK = "_selected_block_id"


@page_registry.register
class ReportEditorPage(Page):
    info = PluginInfo(id="report_editor", name="Report Editor", category="page")
    section = "Workspace"
    icon = "reports"
    order = 31
    min_role = Role.READ_ONLY          # viewing is open; edits are permission-checked

    def render(self, shell) -> None:
        reports = getattr(shell.platform, "reports", None) if shell.platform else None
        report_id = st.session_state.get(OPEN_REPORT)
        if reports is None:
            st.info("Reports engine unavailable.")
            return
        if not report_id:
            st.title("Report Editor")
            st.info("Open a report from **Reports** to start editing.")
            return

        record = reports.get(report_id)
        if record is None:
            st.warning("That report no longer exists.")
            st.session_state.pop(OPEN_REPORT, None)
            return
        document = reports.document(report_id)

        st.title(document.title)
        st.caption(f"{record.template_id} · owner {record.owner} · updated {record.updated_at} "
                   f"· v{record.version}")

        left, center, right = st.columns([1.1, 2.4, 1.3], gap="medium")
        with left:
            self._structure(shell, reports, report_id, document)
        with center:
            self._preview(shell, reports, report_id)
        with right:
            self._properties(shell, reports, report_id, document, record)

    # ------------------------------------------------------------ left: structure
    def _structure(self, shell, reports, report_id, document) -> None:
        st.subheader("Structure")
        if not document.blocks:
            st.caption("No blocks yet — add one from Properties.")
        for i, block in enumerate(document.blocks):
            label = block.title or f"{block.kind.title()} {i + 1}"
            with st.container(border=True):
                st.markdown(f"**{label}**  \n`{block.kind}`"
                            + ("  · hidden" if block.hidden else ""))
                c1, c2, c3, c4, c5 = st.columns(5)
                if c1.button("Up", key=f"up_{block.id}", disabled=i == 0):
                    self._mutate(shell, reports, report_id, lambda d, b=block.id: move_block(d, b, -1))
                if c2.button("Dn", key=f"dn_{block.id}", disabled=i == len(document.blocks) - 1):
                    self._mutate(shell, reports, report_id, lambda d, b=block.id: move_block(d, b, +1))
                if c3.button("Dup", key=f"dup_{block.id}"):
                    self._mutate(shell, reports, report_id, lambda d, b=block.id: duplicate_block(d, b))
                if c4.button("Hide" if not block.hidden else "Show", key=f"hide_{block.id}"):
                    self._mutate(shell, reports, report_id,
                                 lambda d, b=block.id, h=not block.hidden: set_hidden(d, b, h))
                if c5.button("Del", key=f"del_{block.id}"):
                    self._mutate(shell, reports, report_id, lambda d, b=block.id: delete_block(d, b))
                if st.button("Edit", key=f"sel_{block.id}", use_container_width=True):
                    st.session_state[SELECTED_BLOCK] = block.id
                    st.rerun()

    # ------------------------------------------------------------ center: preview
    def _preview(self, shell, reports, report_id) -> None:
        st.subheader("Preview")
        try:
            rendered = reports.render(shell.user, report_id, "html")
            st.components.v1.html(rendered.text, height=900, scrolling=True)
        except Exception as exc:
            st.error(f"Preview unavailable: {exc}")

    # ------------------------------------------------------------ right: properties
    def _properties(self, shell, reports, report_id, document, record) -> None:
        st.subheader("Properties")
        tabs = st.tabs(["Block", "Add", "Document", "Versions"])

        with tabs[0]:
            self._block_properties(shell, reports, report_id, document)
        with tabs[1]:
            self._add_block(shell, reports, report_id, record)
        with tabs[2]:
            self._document_properties(shell, reports, report_id, document)
        with tabs[3]:
            self._versions(shell, reports, report_id)

    def _block_properties(self, shell, reports, report_id, document) -> None:
        block_id = st.session_state.get(SELECTED_BLOCK)
        block = next((b for b in document.blocks if b.id == block_id), None)
        if block is None:
            st.caption("Select a block (Edit) to change its properties.")
            return
        title = st.text_input("Block title", value=block.title, key=f"t_{block.id}")
        if block.kind == "text":
            body = st.text_area("Text  ( # heading · - bullet )", value=block.payload.get("text", ""),
                                height=260, key=f"x_{block.id}")
            payload = {"text": body}
        elif block.kind == "image":
            width = st.slider("Width %", 20, 100, int(block.payload.get("width_pct", 100)),
                              key=f"w_{block.id}")
            caption = st.text_input("Caption", value=block.payload.get("caption", ""),
                                    key=f"c_{block.id}")
            payload = {**block.payload, "width_pct": width, "caption": caption}
        else:
            caption = st.text_input("Caption", value=block.payload.get("caption", ""),
                                    key=f"cc_{block.id}")
            payload = {**block.payload, "caption": caption}
        if st.button("Apply", type="primary", key=f"ap_{block.id}"):
            def _apply(doc, bid=block.id, t=title, p=payload):
                for b in doc.blocks:
                    if b.id == bid:
                        b.title, b.payload = t, p
            self._mutate(shell, reports, report_id, _apply)

    def _add_block(self, shell, reports, report_id, record) -> None:
        kind = st.radio("Block type", ["Text", "Chart", "Image"], horizontal=True,
                        key="new_block_kind")
        if kind == "Text":
            if st.button("Add text block", type="primary", key="add_text"):
                self._mutate(shell, reports, report_id,
                             lambda d: add_block(d, text_block("# Heading\n\nWrite here…",
                                                               title="Text")))
        elif kind == "Chart":
            self._chart_picker(shell, reports, report_id, record)
        else:
            self._image_manager(shell, reports, report_id, record)

    # -- chart picker: driven entirely by the visualization registry ---
    def _chart_picker(self, shell, reports, report_id, record) -> None:
        from fap.visuals.base import load_builtin_visuals, visual_registry
        load_builtin_visuals()
        infos = visual_registry.infos()
        categories = sorted({i.category or "Other" for i in infos})
        category = st.selectbox("Category", categories, key="pick_cat")
        options = [i for i in infos if (i.category or "Other") == category]
        labels = {i.id: i.name for i in options}
        viz_id = st.selectbox("Visualization", list(labels), format_func=lambda i: labels[i],
                              key="pick_viz")
        info = next(i for i in options if i.id == viz_id)
        if info.description:
            st.caption(info.description)
        frame = reports.dataset_frame(record.dataset_id)
        if st.toggle("Preview", key="pick_preview") and frame is not None:
            png = reports.preview_chart(viz_id, frame, {})
            if png:
                st.image(png, use_container_width=True)
            else:
                st.caption("This visualization needs controls the picker does not set yet.")
        if st.button("Insert chart", type="primary", key="add_chart"):
            self._mutate(shell, reports, report_id,
                         lambda d, v=viz_id, n=info.name: add_block(d, chart_block(v, {}, title=n)))

    # -- image manager: upload once, reference by id -------------------
    def _image_manager(self, shell, reports, report_id, record) -> None:
        upload = st.file_uploader("Upload image", type=["png", "jpg", "jpeg", "svg", "webp"],
                                  key="img_up")
        if upload is not None and st.button("Add image", type="primary", key="add_img"):
            try:
                img = reports.upload_image(shell.user, upload.getvalue(), upload.name,
                                           upload.type or "image/png",
                                           workspace_id=record.workspace_id)
                self._mutate(shell, reports, report_id,
                             lambda d, i=img.id, n=upload.name: add_block(d, image_block(i, caption=n)))
            except Exception as exc:
                st.error(f"Could not add image: {exc}")
        existing = reports.list_images(record.workspace_id)
        if existing:
            names = {i.id: f"{i.filename} ({i.size_bytes // 1024}KB)" for i in existing}
            chosen = st.selectbox("Or reuse an uploaded image", list(names),
                                  format_func=lambda i: names[i], key="img_pick")
            if st.button("Insert image", key="ins_img"):
                self._mutate(shell, reports, report_id,
                             lambda d, i=chosen: add_block(d, image_block(i)))

    def _document_properties(self, shell, reports, report_id, document) -> None:
        title = st.text_input("Title", value=document.title, key="doc_title")
        subtitle = st.text_input("Subtitle", value=document.cover.subtitle, key="doc_sub")
        notes = st.text_area("Notes", value=document.notes, height=120, key="doc_notes")
        if st.button("Apply", type="primary", key="doc_apply"):
            def _apply(doc, t=title, s=subtitle, n=notes):
                doc.title, doc.cover.title, doc.cover.subtitle, doc.notes = t, t, s, n
            self._mutate(shell, reports, report_id, _apply)
        st.divider()
        new_title = st.text_input("Save as… (new title)", key="save_as_title")
        if st.button("Save as copy", key="save_as") and new_title.strip():
            copy = reports.save_as(shell.user, report_id, new_title.strip())
            st.session_state[OPEN_REPORT] = copy.id
            st.rerun()

    def _versions(self, shell, reports, report_id) -> None:
        note = st.text_input("Snapshot note", key="ver_note")
        if st.button("Save version", type="primary", key="save_ver"):
            reports.save_version(shell.user, report_id, note=note)
            st.rerun()
        for v in reports.list_versions(report_id):
            with st.container(border=True):
                st.markdown(f"**v{v.version}** · {v.created_at}  \n{v.note or '_no note_'}")
                if st.button("Restore", key=f"rv_{v.id}"):
                    reports.restore_version(shell.user, report_id, v.version)
                    st.rerun()

    # ------------------------------------------------------------ autosave
    @staticmethod
    def _mutate(shell, reports, report_id, fn) -> None:
        """Every edit is persisted immediately (autosave) - no Save required."""
        try:
            reports.update_blocks(shell.user, report_id, fn)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
