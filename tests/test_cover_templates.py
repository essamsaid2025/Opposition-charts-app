"""Report Studio cover system - Right To Dream templates, full field editability,
and the scouting-report player variant (content/config work over the existing
LayoutEngine; the rendering engine architecture is unchanged).

Follows the headless patterns in test_reports.py: build a ReportDocument, attach a
CoverDesign via PublishSettings, and render with the pure LayoutEngine - no Streamlit.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from fap.reports.layout import LayoutEngine, _token_ctx
from fap.reports.models import Cover, ReportDocument
from fap.reports.publishing import CoverDesign, PublishSettings
from fap.ui.studio.covers import COVER_PRESETS, COVER_TEMPLATES, template_design

RTD_DARK = "Right To Dream Dark"
RTD_LIGHT = "Right To Dream Light"


# ---------------------------------------------------------------- helpers
def _doc(design_name=None, **cover_kw):
    cover = Cover(title=cover_kw.pop("title", "Report"), **cover_kw)
    doc = ReportDocument(id="d1", title=cover.title, cover=cover)
    if design_name is not None:
        settings = PublishSettings(cover=CoverDesign(**template_design(design_name)))
        settings.write_to(doc)
    return doc


def _cover_page(doc, resolver=None):
    return LayoutEngine().build(doc, image_resolver=resolver).pages[0]


def _meta_text(page):
    return "\n".join(e.content.get("text", "") for e in page.elements
                     if e.kind == "text" and e.role == "meta")


def _divider_color(page):
    return next((e.content.get("color") for e in page.elements if e.kind == "divider"), None)


def _logos(page):
    return [e for e in page.elements if e.kind == "logo"]


# ---------------------------------------------------------------- Part 1: templates + colours
def test_rtd_templates_registered_with_exact_values():
    dark, light = COVER_TEMPLATES[RTD_DARK], COVER_TEMPLATES[RTD_LIGHT]
    assert dark["background_color"] == "#000000" and light["background_color"] == "#ffffff"
    # accent sampled from the Right To Dream logo - exact, identical on both
    assert dark["accent_color"] == "#eca137" and light["accent_color"] == "#eca137"
    assert dark["text_color"] == "#ffffff" and light["text_color"] == "#111111"
    for t in (dark, light):
        assert t["alignment"] == "left" and t["divider"] is True
        assert t["logo_position"] == "spread"


def test_rtd_templates_render_exact_colours():
    for name, bg in ((RTD_DARK, "#000000"), (RTD_LIGHT, "#ffffff")):
        page = _cover_page(_doc(name, title="RTD", subtitle="Cover"))
        assert page.background_color == bg              # solid page background
        assert _divider_color(page) == "#eca137"        # accent divider, exact


def test_rtd_spread_logos_at_opposite_corners():
    doc = _doc(RTD_DARK, title="RTD", club_logo="club", organization_logo="org")
    page = _cover_page(doc, resolver=lambda _id: b"\x89PNG\r\n\x1a\n")
    logos = _logos(page)
    assert len(logos) == 2
    club_logo, org_logo = logos                          # club appended first, org second
    assert (club_logo.fx, club_logo.fy) == (0.08, 0.06)  # club -> top-LEFT
    assert (org_logo.fx, org_logo.fy) == (0.80, 0.06)    # organization -> top-RIGHT
    assert club_logo.fw == 0.12 and org_logo.fw == 0.12


def test_scouting_preset_points_at_rtd_and_nothing_deleted():
    assert COVER_PRESETS["Scouting Report"] == RTD_DARK
    # the previously-mapped template is still available (not deleted)
    assert "Recruitment Report" in COVER_TEMPLATES


# ---------------------------------------------------------------- Part 2: every field editable + renders
# Mirrors the Studio cover form's save-back logic (editor.py `m()`): assign each edited
# value onto document.cover, then render. Every field that appears on the cover round-trips.
_META_FIELDS = dict(competition="UEFA WCL", season="25/26", opponent="Rival FC",
                    match_date="2026-08-08", analyst="Ada Lovelace", version="2.3")


def test_all_meta_fields_round_trip_to_rendered_cover():
    doc = _doc(RTD_DARK, title="Match", **_META_FIELDS)
    text = _meta_text(_cover_page(doc))
    assert "UEFA WCL" in text and "25/26" in text
    assert "vs Rival FC" in text and "2026-08-08" in text
    assert "Ada Lovelace" in text and "v2.3" in text


def test_club_and_organization_round_trip_to_render_tokens():
    # club/organization feed header/footer tokens ({club}/{organization}), not meta_lines
    cover = Cover(title="T", club="Right To Dream", organization="RTD Global")
    ctx = _token_ctx(cover, _cover_page(ReportDocument(id="d", title="T", cover=cover)),
                     PublishSettings())
    assert ctx["club"] == "Right To Dream" and ctx["organization"] == "RTD Global"
    # and they survive a full JSON round-trip of the document
    restored = ReportDocument.from_dict(ReportDocument(id="d", title="T", cover=cover).to_dict())
    assert restored.cover.club == "Right To Dream" and restored.cover.organization == "RTD Global"


# ---------------------------------------------------------------- Part 3: player variant
def test_player_field_round_trips_through_json():
    cover = Cover(title="Scout", player="Kwame Mensah")
    restored = ReportDocument.from_dict(ReportDocument(id="d", title="Scout", cover=cover).to_dict())
    assert restored.cover.player == "Kwame Mensah"


def test_player_set_shows_player_line_not_vs_opponent():
    doc = _doc(RTD_DARK, title="Scout", player="Kwame Mensah", club="Right To Dream",
               opponent="Rival FC", match_date="2026-08-08")
    text = _meta_text(_cover_page(doc))
    assert "Kwame Mensah · Right To Dream" in text       # player-appropriate line
    assert "vs Rival FC" not in text                     # opponent match framing suppressed


def test_player_empty_keeps_opponent_behaviour_unchanged():
    doc = _doc(RTD_DARK, title="Match", opponent="Rival FC", match_date="2026-08-08")
    text = _meta_text(_cover_page(doc))
    assert "vs Rival FC" in text and "2026-08-08" in text


# ---------------------------------------------------------------- Part 2(d): regression guard
def test_existing_templates_and_presets_unaffected():
    # a couple of pre-existing templates keep their exact design values
    assert COVER_TEMPLATES["Minimal White"] == dict(
        template="minimal_white", background_color="#ffffff", overlay_opacity=0.0,
        alignment="left", accent_color="#E07B2B", text_color="#16181d",
        divider=True, logo_position="top")
    assert COVER_TEMPLATES["Club Branding"]["accent_color"] == "#d4af37"
    # every original preset key still present; only Scouting Report was repointed
    for key in ("Player Report", "Opponent Report", "Match Report", "Tournament Report",
                "Academy Report", "Weekly Report", "Monthly Report"):
        assert key in COVER_PRESETS
    assert COVER_PRESETS["Opponent Report"] == "Opposition Report"


def test_existing_logo_positions_unchanged_by_spread_addition():
    # adding "spread" must not move logos for the classic positions
    doc = _doc("Minimal White", title="T", club_logo="c", organization_logo="o")
    logos = _logos(_cover_page(doc, resolver=lambda _id: b"\x89PNG\r\n\x1a\n"))
    assert (logos[0].fx, logos[0].fy) == (0.08, 0.10)    # top: club at lx
    assert round(logos[1].fx, 2) == 0.22                 # top: org adjacent (lx + 0.14)
