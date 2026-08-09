"""Free-form canvas Phase 2 — resize + per-block typography/colour overrides.

The JS resize/drag surface (report_canvas/index.html) is browser-only and NOT unit-tested
here (we don't fake that coverage). These tests cover the pure Python:

(a) the resize ``update_layout`` command validates, snaps, clamps and respects locked blocks;
(b) a style override is honoured CONSISTENTLY in all three export backends (HTML string, PDF
    text-style resolver, DOCX run overrides, PPTX text style) — the same override, everywhere;
(c) THE critical regression: a block with NO override resolves to the exact role-based theme
    default in every backend (byte-identical to before this phase), across three shared backends;
(d) "reset to theme default" removes the override key entirely.

Follows tests/test_report_canvas.py and tests/test_reports.py patterns.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from fap.reports import _office, _pdf, text_block
from fap.reports import exporters as EX
from fap.reports.block_style import (
    FONT_FAMILIES, clean_style, font_for, hex_to_rgb, html_style_css,
)
from fap.reports.editor_ops import create_page
from fap.reports.layout import LayoutEngine
from fap.reports.models import Cover, ReportDocument
from fap.reports.renderer import ReportRenderer
from fap.reports.studio import ReportStudio
from fap.ui.builtin.report_canvas import parse_result
from fap.ui.studio import editor as ED

INK, MUTED = "#16181d", "#5b6472"
STYLE = {"font_size": 28, "font_family": "Serif", "color": "#ff0000"}


def _elements(styled_style=None):
    """Return (styled_element, plain_element) built through the real layout engine."""
    doc = ReportDocument(id="d", title="T", cover=Cover(title="T"))
    studio = ReportStudio.from_document(doc)
    styled = text_block("Styled heading", title="S")
    if styled_style is not None:
        styled.payload["style"] = styled_style
    plain = text_block("Plain body", title="P")
    studio.document.blocks += [styled, plain]
    ED._reflow(studio)
    rd = LayoutEngine().build(studio.to_document())
    es = next(e for p in rd.pages for e in p.elements if e.content.get("text") == "Styled heading")
    ep = next(e for p in rd.pages for e in p.elements if e.content.get("text") == "Plain body")
    return es, ep


# ---------------------------------------------------------------- clean_style / helpers
def test_clean_style_keeps_only_valid_present_keys():
    assert clean_style({"font_size": 20, "font_family": "Serif", "color": "#ff0000"}) == {
        "font_size": 20, "font_family": "Serif", "color": "#ff0000"}
    assert clean_style({}) == {} and clean_style(None) == {} and clean_style("x") == {}
    assert clean_style({"font_size": 0}) == {}                 # non-positive dropped
    assert clean_style({"font_size": True}) == {}              # bool is not a size
    assert clean_style({"font_family": "Comic"}) == {}         # not in the curated set
    assert clean_style({"color": "   "}) == {}                 # blank dropped
    assert clean_style({"font_size": 999}) == {"font_size": 96}   # clamped to MAX


def test_hex_to_rgb():
    assert hex_to_rgb("#ff8800") == (255, 136, 0)
    assert hex_to_rgb("#abc") == (170, 187, 204)               # 3-char short form
    assert hex_to_rgb("zzzzzz") is None and hex_to_rgb(None) is None


def test_font_family_list_covers_all_backends():
    for label, spec in FONT_FAMILIES.items():
        assert set(spec) == {"html", "mpl", "office"} and all(spec.values())


# ---------------------------------------------------------------- (b) override honoured everywhere
def test_html_backend_honours_override():
    es, _ = _elements(STYLE)
    html = EX._element_html(es)
    assert "font-size:28px" in html
    assert "#ff0000" in html
    assert "serif" in html                                     # the Serif html stack


def test_pdf_backend_honours_override():
    es, _ = _elements(STYLE)
    size, color, weight, family = _pdf._text_style(es, INK, MUTED)
    assert size == 28 and color == "#ff0000" and family == "serif"


def test_office_backends_honour_override():
    es, _ = _elements(STYLE)
    assert _office.docx_run_overrides(es.content.get("style")) == {
        "size": 28, "name": "Georgia", "rgb": (255, 0, 0)}
    assert _office.pptx_text_style(es.role, es.content.get("style")) == (28, "Georgia", (255, 0, 0))


def test_full_html_export_end_to_end_carries_override():
    doc = ReportDocument(id="d", title="T", cover=Cover(title="T"))
    studio = ReportStudio.from_document(doc)
    b = text_block("Big red", title="B")
    b.payload["style"] = {"font_size": 40, "color": "#00aa00"}
    studio.document.blocks.append(b)
    ED._reflow(studio)
    out = ReportRenderer().render(studio.to_document(), "html").content
    assert b"font-size:40px" in out and b"#00aa00" in out


def test_full_pdf_export_with_override_does_not_crash():
    doc = ReportDocument(id="d", title="T", cover=Cover(title="T"))
    studio = ReportStudio.from_document(doc)
    b = text_block("Styled", title="B")
    b.payload["style"] = dict(STYLE)
    studio.document.blocks.append(b)
    ED._reflow(studio)
    pdf = _pdf.render_pdf(LayoutEngine().build(studio.to_document()))
    assert pdf[:5] == b"%PDF-" and len(pdf) > 500


# ---------------------------------------------------------------- (c) NO override == identical
def test_no_override_html_wrapper_has_no_injected_font_css():
    _, ep = _elements(None)
    assert ep.content.get("style") is None                     # nothing plumbed through
    wrapper = EX._element_html(ep).split(">", 1)[0]            # the opening <div ...> only
    assert "font-size:" not in wrapper
    assert "font-family:" not in wrapper
    assert "color:" not in wrapper


def test_no_override_pdf_uses_exact_role_default():
    _, ep = _elements(None)
    # matches the pre-phase role-only styling exactly: body role -> 11pt, ink, normal, no family
    assert _pdf._text_style(ep, INK, MUTED) == (11, INK, "normal", None)


def test_no_override_office_is_noop():
    _, ep = _elements(None)
    assert _office.docx_run_overrides(ep.content.get("style")) is None
    assert _office.pptx_text_style(ep.role, ep.content.get("style")) == (14, None, None)


def test_html_style_css_empty_when_absent():
    assert html_style_css(None) == "" and html_style_css({}) == ""


# ---------------------------------------------------------------- (d) reset clears
def test_reset_removes_the_style_key():
    doc = ReportDocument(id="d", title="T", cover=Cover(title="T"))
    studio = ReportStudio.from_document(doc)
    b = text_block("x", title="X")
    b.payload["style"] = dict(STYLE)
    studio.document.blocks.append(b)
    ED._set_style(studio, b.id, {})                            # reset
    assert "style" not in b.payload


def test_set_style_stores_cleaned_override():
    doc = ReportDocument(id="d", title="T", cover=Cover(title="T"))
    studio = ReportStudio.from_document(doc)
    b = text_block("x", title="X")
    studio.document.blocks.append(b)
    ED._set_style(studio, b.id, {"font_size": 22, "font_family": "Bogus", "color": "#123456"})
    # invalid family dropped, valid fields kept
    assert b.payload["style"] == {"font_size": 22, "color": "#123456"}


# ---------------------------------------------------------------- (a) resize command
def test_parse_result_accepts_resize_and_move_resize():
    assert parse_result({"ts": 1, "commands": [
        {"op": "update_layout", "id": "a", "width": 100, "height": 80}]}) == {
        "ts": 1.0, "commands": [{"op": "update_layout", "id": "a", "width": 100.0, "height": 80.0}]}
    assert parse_result({"ts": 1, "commands": [
        {"op": "update_layout", "id": "a", "x": 5, "width": 100}]})["commands"][0] == {
        "op": "update_layout", "id": "a", "x": 5.0, "width": 100.0}


def test_parse_result_rejects_empty_and_bad_geometry():
    assert parse_result({"ts": 1, "commands": [{"op": "update_layout", "id": "a"}]}) is None
    assert parse_result({"ts": 1, "commands": [
        {"op": "update_layout", "id": "a", "width": True}]}) is None


def _free_block():
    doc = ReportDocument(id="d", title="T", cover=Cover(title="T"))
    studio = ReportStudio.from_document(doc)
    create_page(studio, title="Free", kind="free")
    b = text_block("x", title="X")
    ED._add_block(studio, b)
    return studio, b


def test_resize_snaps_and_floors_at_min():
    studio, b = _free_block()
    studio.editor.snap_to_grid = True
    studio.editor.grid_size = 8
    ED._apply_layout_cmds(studio, [{"op": "update_layout", "id": b.id, "width": 201, "height": 305}])
    assert studio.layouts[b.id].width == 200 and studio.layouts[b.id].height == 304   # snapped to 8
    ED._apply_layout_cmds(studio, [{"op": "update_layout", "id": b.id, "width": 3, "height": 3}])
    assert studio.layouts[b.id].width == ED._MIN_BLOCK and studio.layouts[b.id].height == ED._MIN_BLOCK


def test_resize_clamps_within_page():
    studio, b = _free_block()
    studio.editor.snap_to_grid = False
    pw, ph = studio.pages[-1].dimensions()
    studio.layouts[b.id].x, studio.layouts[b.id].y = 100.0, 120.0
    ED._apply_layout_cmds(studio, [{"op": "update_layout", "id": b.id, "width": 99999, "height": 99999}])
    assert studio.layouts[b.id].width == pw - 100.0 and studio.layouts[b.id].height == ph - 120.0


def test_resize_ignores_locked_block():
    studio, b = _free_block()
    studio.layouts[b.id].width, studio.layouts[b.id].height = 200.0, 150.0
    studio.layouts[b.id].locked = True
    ED._apply_layout_cmds(studio, [{"op": "update_layout", "id": b.id, "width": 400, "height": 400}])
    assert (studio.layouts[b.id].width, studio.layouts[b.id].height) == (200.0, 150.0)


def test_move_only_command_still_works_unchanged():
    studio, b = _free_block()
    studio.editor.snap_to_grid = False
    ED._apply_layout_cmds(studio, [{"op": "update_layout", "id": b.id, "x": 60, "y": 70}])
    assert (studio.layouts[b.id].x, studio.layouts[b.id].y) == (60.0, 70.0)
