"""Assign scouting charts to a player and download a report containing them.

Proves the reuse-only flow: a rendered chart is frozen as a PNG and pinned to the
player (ImageStorage, kind 'report_chart'), embedded into the player's report as an
image block, and the existing reports engine renders a downloadable file with the
chart inlined. No new storage tier, no second report editor, no chart code.
"""
import base64
import os
import pathlib
import sys
from dataclasses import replace

os.environ["FAP_TEST"] = "1"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pytest

from fap.bootstrap import init_platform
from fap.config.settings import AppSettings, CacheSettings, DatabaseSettings, StorageSettings
from fap.identity.models import User
from fap.identity.roles import Role

# a real 1x1 PNG so every exporter (incl. matplotlib PDF) can decode it
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture
def platform(tmp_path):
    settings = replace(
        AppSettings(environment="development"), user_data_dir=str(tmp_path / "ud"),
        database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
        cache=CacheSettings(backend="memory"), storage=StorageSettings(backend="local"))
    p = init_platform(settings=settings)
    yield p
    p.db.close()


@pytest.fixture
def user():
    return User(email="scout@club.com", name="Scout", role=Role.SUPER_ADMIN, provider_id="dev")


def test_assigned_charts_are_separate_media(platform, user):
    svc = platform.scouting
    p = svc.create_player(user, "Mohamed Shika", position="RW")
    svc.assign_chart(user, p.id, _PNG, title="Heat map", viz_id="occupation_map")
    svc.add_image(user, p.id, _PNG, "image/png", kind="scouting", caption="squad photo")

    charts = svc.list_assigned_charts(p.id)
    assert len(charts) == 1 and charts[0].kind == "report_chart"
    # the Images tab lists non-chart media only
    non_chart = [m for m in svc.list_media(p.id) if m.kind != "report_chart"]
    assert len(non_chart) == 1 and non_chart[0].kind == "scouting"


def test_generated_report_embeds_assigned_charts(platform, user):
    svc, reports = platform.scouting, platform.reports
    p = svc.create_player(user, "Mohamed Shika", position="RW")
    m1 = svc.assign_chart(user, p.id, _PNG, title="Heat map")
    m2 = svc.assign_chart(user, p.id, _PNG, title="Shot map")

    link = svc.create_report(user, p.id)
    doc = reports.document(link.report_id)
    image_ids = {b.payload.get("image_id") for b in doc.blocks if b.kind == "image"}
    assert image_ids == {m1.image_id, m2.image_id}


def test_download_report_contains_the_chart(platform, user):
    svc = platform.scouting
    p = svc.create_player(user, "Mohamed Shika")
    svc.assign_chart(user, p.id, _PNG, title="Heat map")
    link = svc.create_report(user, p.id)

    formats = svc.report_formats()
    assert "html" in formats
    html = svc.render_report(user, link.report_id, "html")
    assert html.content and html.mime == "text/html"
    assert base64.b64encode(_PNG).decode("ascii") in html.content.decode("utf-8")


def test_add_charts_to_existing_report(platform, user):
    svc, reports = platform.scouting, platform.reports
    p = svc.create_player(user, "Mohamed Shika")
    svc.assign_chart(user, p.id, _PNG, title="Heat map")

    link = svc.create_report(user, p.id, include_charts=False)
    assert not [b for b in reports.document(link.report_id).blocks if b.kind == "image"]

    added = svc.add_charts_to_report(user, link.report_id, p.id)
    assert added == 1
    assert len([b for b in reports.document(link.report_id).blocks if b.kind == "image"]) == 1


def test_unassign_removes_the_chart(platform, user):
    svc = platform.scouting
    p = svc.create_player(user, "Mohamed Shika")
    m = svc.assign_chart(user, p.id, _PNG, title="Heat map")
    assert len(svc.list_assigned_charts(p.id)) == 1
    svc.unassign_chart(user, m.id)
    assert svc.list_assigned_charts(p.id) == []
