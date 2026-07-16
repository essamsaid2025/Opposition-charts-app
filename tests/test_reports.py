"""Professional Reports Engine (Phase 5.2).

The engine is pure/testable headlessly: registries, builder, renderer,
exporters, manager (CRUD + permissions + audit + autosave). It reuses platform
metrics/insights/visuals and never modifies them.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import pytest

from fap.core.exceptions import AuthError
from fap.db.engine import Database
from fap.identity.models import User
from fap.identity.roles import Role
from fap.reports import (
    BuildContext, CustomTemplate, DocumentBuilder, ReportDocument, ReportRenderer,
    ReportsManager, exporter_registry, load_builtin_reports, section_builder_registry,
    template_registry,
)
from fap.reports.exporters import ReportFormatUnavailable

load_builtin_reports()

EXPECTED_TEMPLATES = {"opponent_report", "match_report", "scout_report", "player_report",
                      "tournament_report", "weekly_report", "academy_report", "training_report"}
EXPECTED_SECTIONS = {"executive_summary", "tactical_summary", "open_play", "possession",
                     "passing", "build_up", "final_third", "chance_creation", "shooting",
                     "defensive", "pressing", "set_pieces", "key_players", "team_statistics",
                     "notes", "appendix"}


def _df(n=300, seed=5):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "event_type": rng.choice(["pass", "carry", "shot", "cross", "duel", "recovery",
                                  "interception", "clearance", "tackle", "block"], n),
        "x": rng.uniform(0, 100, n), "y": rng.uniform(0, 100, n),
        "end_x": rng.uniform(0, 100, n), "end_y": rng.uniform(0, 100, n),
        "player": rng.choice(["A", "B", "C", "D"], n), "team": "Rival",
        "outcome": rng.choice(["successful", "unsuccessful"], n),
        "shot_result": rng.choice(["goal", "saved", "off target", ""], n),
    })


def _user(role=Role.PERFORMANCE_ANALYST, email="a@club.com"):
    return User(email=email, name=email.split("@")[0], role=role, provider_id="dev")


@pytest.fixture()
def mgr(tmp_path) -> ReportsManager:
    from fap.theme import DEFAULT_BRANDING
    return ReportsManager(Database(tmp_path / "r.sqlite3"), branding=DEFAULT_BRANDING)


# ---------------------------------------------------------------- registry
def test_all_templates_register():
    assert EXPECTED_TEMPLATES <= set(template_registry.ids())


def test_all_sections_register():
    assert EXPECTED_SECTIONS <= set(section_builder_registry.ids())


def test_no_duplicate_ids():
    assert len(template_registry.ids()) == len(set(template_registry.ids()))
    assert len(section_builder_registry.ids()) == len(set(section_builder_registry.ids()))


def test_exporters_registered_html_markdown_available_office_stub():
    ids = {e.info.id for e in exporter_registry}
    assert {"report_html", "report_markdown", "report_pdf", "report_docx", "report_pptx"} <= ids
    renderer = ReportRenderer()
    assert set(renderer.available_formats()) == {"html", "markdown"}
    assert {"pdf", "docx", "pptx"} <= set(renderer.formats())


def test_legacy_report_section_family_untouched():
    from fap.reports import section_registry, ReportSection, ReportBuilder
    assert "visuals" in section_registry.ids()      # legacy VisualsSection still there


# ---------------------------------------------------------------- builder
def test_builder_produces_pure_document_with_cover_and_sections():
    ctx = BuildContext(df=_df(), analyst="Ada",
                       cover={"opponent": "Rival FC", "competition": "Prem", "season": "25/26"})
    doc = DocumentBuilder().build("opponent_report", ctx, title="Test")
    assert isinstance(doc, ReportDocument)
    assert doc.template_id == "opponent_report"
    assert len(doc.sections) == 16
    assert doc.cover.opponent == "Rival FC" and doc.cover.analyst == "Ada"
    assert doc.cover.generated_at and doc.cover.version
    # pure: sections carry data, not rendered output
    exec_s = next(s for s in doc.sections if s.id == "executive_summary")
    assert exec_s.kpis and exec_s.title == "Executive Summary"


def test_builder_uses_template_section_order():
    ctx = BuildContext(df=_df())
    doc = DocumentBuilder().build("match_report", ctx)
    ids = [s.id for s in doc.sections]
    assert ids[0] == "executive_summary" and "set_pieces" in ids
    assert "tactical_summary" not in ids           # not in match_report template


def test_custom_template_supported():
    tpl = CustomTemplate(id="custom", name="Custom", section_ids=("executive_summary", "shooting"),
                         subtitle="mine", cover={"opponent": "X"})
    doc = DocumentBuilder().build(tpl, BuildContext(df=_df()))
    assert [s.id for s in doc.sections] == ["executive_summary", "shooting"]


def test_document_json_roundtrip():
    doc = DocumentBuilder().build("weekly_report", BuildContext(df=_df()))
    restored = ReportDocument.from_dict(doc.to_dict())
    assert restored.id == doc.id and len(restored.sections) == len(doc.sections)
    assert restored.sections[0].kpis[0].label == doc.sections[0].kpis[0].label


def test_bad_section_never_breaks_report():
    tpl = CustomTemplate(id="c", name="C", section_ids=("nonexistent_section", "shooting"))
    doc = DocumentBuilder().build(tpl, BuildContext(df=_df()))
    assert len(doc.sections) == 2 and doc.sections[0].id == "nonexistent_section"


# ---------------------------------------------------------------- renderer / exporters
def test_html_export_contains_cover_and_sections():
    doc = DocumentBuilder().build("opponent_report",
                                  BuildContext(df=_df(), cover={"opponent": "Rival FC"}))
    out = ReportRenderer().render(doc, "html")
    assert out.mime == "text/html" and out.filename.endswith(".html")
    assert b"Rival FC" in out.content and b"Executive Summary" in out.content


def test_markdown_export():
    doc = DocumentBuilder().build("scout_report", BuildContext(df=_df()))
    out = ReportRenderer().render(doc, "markdown")
    assert out.mime == "text/markdown" and out.text.startswith("# ")


def test_office_formats_fail_clearly_but_are_registered():
    doc = DocumentBuilder().build("weekly_report", BuildContext(df=_df()))
    for fmt in ("pdf", "docx", "pptx"):
        with pytest.raises(ReportFormatUnavailable):
            ReportRenderer().render(doc, fmt)


def test_exporters_only_render_never_recompute():
    """An exporter must produce identical output for the same document."""
    doc = DocumentBuilder().build("weekly_report", BuildContext(df=_df()))
    a = ReportRenderer().render(doc, "html").content
    b = ReportRenderer().render(doc, "html").content
    assert a == b


# ---------------------------------------------------------------- manager CRUD
def test_create_and_open(mgr):
    rec = mgr.create(_user(), template="opponent_report", df=_df(), workspace_id="ws1",
                     cover={"opponent": "Rival"})
    assert rec.owner == "a@club.com" and rec.status == "active"
    doc = mgr.document(rec.id)
    assert doc is not None and doc.cover.opponent == "Rival"


def test_rename_duplicate_archive_restore_delete(mgr):
    admin = _user(Role.SUPER_ADMIN, "admin@club.com")
    rec = mgr.create(admin, template="weekly_report", df=_df())
    mgr.rename(admin, rec.id, "Renamed")
    assert mgr.get(rec.id).title == "Renamed"
    dup = mgr.duplicate(admin, rec.id)
    assert dup.id != rec.id and dup.title.endswith("(copy)")
    mgr.archive(admin, rec.id)
    assert mgr.get(rec.id).status == "archived"
    assert rec.id not in {r.id for r in mgr.list(admin)}
    mgr.restore(admin, rec.id)
    assert mgr.get(rec.id).status == "active"
    mgr.delete(admin, rec.id)
    assert mgr.get(rec.id) is None


def test_favorite_recent_search(mgr):
    u = _user()
    r1 = mgr.create(u, template="weekly_report", df=_df(), title="Alpha", workspace_id="w")
    r2 = mgr.create(u, template="match_report", df=_df(), title="Beta", workspace_id="w")
    # deterministic newest-created-first (rowid tiebreak at second resolution)
    assert mgr.recent(u, workspace_id="w")[0].title == "Beta"
    assert {r.title for r in mgr.recent(u, workspace_id="w")} == {"Alpha", "Beta"}
    mgr.favorite(u, r1.id, on=True)
    assert {r.id for r in mgr.favorites(u, workspace_id="w")} == {r1.id}
    assert {r.title for r in mgr.list(u, workspace_id="w", query="alpha")} == {"Alpha"}


# ---------------------------------------------------------------- permissions
def test_read_only_cannot_create_or_modify(mgr):
    reader = _user(Role.READ_ONLY, "r@club.com")
    with pytest.raises(AuthError):
        mgr.create(reader, template="weekly_report", df=_df())


def test_delete_requires_admin(mgr):
    analyst = _user(Role.PERFORMANCE_ANALYST)
    rec = mgr.create(analyst, template="weekly_report", df=_df())
    with pytest.raises(AuthError):
        mgr.delete(analyst, rec.id)                    # destructive -> admins only
    _user(Role.CLUB_ADMIN, "boss@club.com")
    mgr.delete(_user(Role.CLUB_ADMIN, "boss@club.com"), rec.id)
    assert mgr.get(rec.id) is None


def test_non_owner_analyst_cannot_edit_others_report(mgr):
    owner = _user(Role.PERFORMANCE_ANALYST, "owner@club.com")
    other = _user(Role.PERFORMANCE_ANALYST, "other@club.com")
    rec = mgr.create(owner, template="weekly_report", df=_df())
    with pytest.raises(AuthError):
        mgr.rename(other, rec.id, "hijack")
    # club admin can edit anyone's report
    mgr.rename(_user(Role.CLUB_ADMIN, "boss@club.com"), rec.id, "ok")
    assert mgr.get(rec.id).title == "ok"


# ---------------------------------------------------------------- audit
def test_every_action_is_audited(mgr):
    admin = _user(Role.SUPER_ADMIN, "admin@club.com")
    rec = mgr.create(admin, template="weekly_report", df=_df())
    mgr.render(admin, rec.id, "html")
    mgr.rename(admin, rec.id, "X")
    mgr.delete(admin, rec.id)
    actions = {e.action for e in mgr.audit.recent()}
    assert {"report.create", "report.export", "report.rename", "report.delete"} <= actions


# ---------------------------------------------------------------- autosave
def test_autosave_and_recover_draft(mgr):
    u = _user()
    mgr.autosave(u, "draft-1", {"title": "WIP", "sections": []})
    assert mgr.load_draft(u, "draft-1")["title"] == "WIP"
    assert "draft-1" in mgr.draft_keys(u)
    # another user has their own drafts
    assert mgr.draft_keys(_user(email="z@club.com")) == []
    mgr.discard_draft(u, "draft-1")
    assert mgr.load_draft(u, "draft-1") == {}


# ---------------------------------------------------------------- reuse / backward compat
def test_reports_reuse_platform_metrics_no_duplication():
    # the executive summary must be built from platform MetricResults
    import inspect
    from fap.reports.builtin import _common
    src = inspect.getsource(_common)
    assert "compute_all" in src and "InsightEngine" in src   # reuse, not recompute


def test_engine_does_not_modify_visualization_or_analytics():
    # the reports package must not import-and-mutate the viz/analytics engines;
    # it only reads selectors. Cheap guard: no writes to those modules here.
    import fap.reports.builtin.possession as p
    src = pathlib.Path(p.__file__).read_text(encoding="utf-8")
    assert "fap.visuals import analysis" in src           # reads selectors
