"""Report Studio v2 (Phase A) — architecture-proof tests.

Covers: engine-independent document init/normalize, save/load round-trip through
the existing ReportDocument, engine-independent serialization, the feature flag,
that the classic Report Studio stays registered/default, and that the frontend
assets are present and self-contained (no runtime CDN).
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pytest

from fap.reports import editor_adapter as A
from fap.reports.models import ReportDocument

FRONTEND = (pathlib.Path(__file__).resolve().parent.parent
            / "src/fap/ui/builtin/frontend/report_studio")


# ----------------------------------------------------------- document model
def test_new_document_shape():
    d = A.new_document("My Report")
    assert d["title"] == "My Report"
    assert d["schema_version"] == A.SCHEMA_VERSION
    assert len(d["pages"]) == 1 and d["pages"][0]["elements"] == []
    assert d["active_page"] == d["pages"][0]["id"]
    assert set(d["theme"]) >= {"background", "accent"}
    assert A.validate(d) == []


def test_normalize_fills_defaults_and_ids():
    raw = {"pages": [{"elements": [{"type": "rect", "x": "10", "y": 20},
                                   {"type": "text", "text": "hi"}]}]}
    d = A.normalize(raw)
    p = d["pages"][0]
    assert p["id"] and d["active_page"] == p["id"]
    assert p["elements"][0]["id"] and p["elements"][1]["id"]
    assert p["elements"][0]["x"] == 10.0 and p["elements"][0]["type"] == "rect"
    assert p["elements"][1]["type"] == "text" and p["elements"][1]["text"] == "hi"


def test_normalize_handles_garbage():
    assert A.normalize(None)["pages"]          # never raises, always >=1 page
    assert A.normalize({})["pages"]
    assert A.validate(A.normalize({"pages": []})) == []


def test_engine_independent_serialization():
    """The persisted element carries only neutral geometry/props — nothing that
    ties it to Konva (no className/attrs/scene-graph fields)."""
    d = A.new_document()
    d["pages"][0]["elements"].append(
        {"id": "r1", "type": "rect", "x": 5, "y": 6, "width": 100, "height": 50,
         "rotation": 0, "fill": "#fff", "stroke": "#000"})
    el = A.normalize(d)["pages"][0]["elements"][0]
    forbidden = {"className", "attrs", "nodeType", "children", "konva"}
    assert not (set(el) & forbidden)
    assert set(el) >= {"id", "type", "x", "y", "width", "height", "rotation"}


# ----------------------------------------------------------- save / load
def test_save_load_round_trip_via_report_document():
    d = A.new_document("Round Trip")
    d["pages"][0]["elements"] = [
        {"id": "t1", "type": "text", "x": 1, "y": 2, "width": 200, "rotation": 0,
         "text": "hello", "fontSize": 24, "fill": "#111"}]
    rd = A.to_report_document(d, report_id=d["id"], title=d["title"])
    # stored additively; classic content untouched
    assert isinstance(rd, ReportDocument)
    assert rd.meta[A.META_KEY]["pages"][0]["elements"][0]["text"] == "hello"
    assert rd.blocks == [] and rd.sections == []
    # survives a full dict serialization cycle (as persistence does)
    rd2 = ReportDocument.from_dict(rd.to_dict())
    back = A.from_report_document(rd2)
    assert back == A.normalize(d)               # exact engine-independent round-trip


def test_legacy_report_opens_as_empty_v2_canvas():
    legacy = ReportDocument(id="rep-9", title="Legacy")
    d = A.from_report_document(legacy)
    assert d["id"] == "rep-9" and d["title"] == "Legacy"
    assert len(d["pages"]) == 1 and d["pages"][0]["elements"] == []


# ----------------------------------------------------------- feature flag
def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("FAP_REPORT_STUDIO_V2", raising=False)
    assert A.v2_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on", "TRUE"])
def test_flag_on_values(monkeypatch, val):
    monkeypatch.setenv("FAP_REPORT_STUDIO_V2", val)
    assert A.v2_enabled() is True


def test_flag_off_values(monkeypatch):
    for val in ["", "0", "false", "no", "off"]:
        monkeypatch.setenv("FAP_REPORT_STUDIO_V2", val)
        assert A.v2_enabled() is False


# ----------------------------------------------------------- registration / classic intact
def test_v2_page_not_registered_by_default_and_classic_intact():
    from fap.ui.page import load_builtin_pages, all_pages
    load_builtin_pages()
    ids = {p.info.id for p in all_pages()}
    assert "report_editor" in ids                 # classic Report Studio still present
    assert "report_studio_v2" not in ids          # v2 hidden while the flag is off


def test_v2_page_class_importable_even_when_flag_off():
    # the class exists (for tests/tooling) even though it is not registered
    from fap.ui.builtin.report_studio import ReportStudioV2Page
    assert ReportStudioV2Page.info.id == "report_studio_v2"
    assert ReportStudioV2Page.section == "Workspace"


# ----------------------------------------------------------- frontend assets / no CDN
def test_frontend_assets_present():
    for f in ["index.html", "app.js", "vendor/react.production.min.js",
              "vendor/react-dom.production.min.js", "vendor/konva.min.js",
              "vendor/htm.umd.js"]:
        assert (FRONTEND / f).exists(), f"missing {f}"


def test_frontend_has_no_runtime_cdn():
    """All libraries are vendored locally; the shipped component must not fetch
    anything from a remote host at runtime (the free/self-hosted requirement)."""
    for name in ["index.html", "app.js"]:
        text = (FRONTEND / name).read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, f"{name} references a URL"
