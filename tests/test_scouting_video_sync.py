"""Click-to-seek video sync (Tier 1) - pure logic + persistence.

The JS component isn't unit-testable via pytest, so this covers the pure Python:
the ``video_time = offset + minute*60 + second`` calculation, provider-id
extraction / seek-mode detection, the ``parse_result`` trust boundary, the two
new persisted fields (model default + migration 12 + repository + service), and -
the key safety property - that an existing video with no match/offset is left in
the exact "render as today" state.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pytest

from fap.db.engine import Database
from fap.identity.models import User
from fap.identity.roles import Role
from fap.scouting.models import Player, PlayerVideo
from fap.scouting.repository import PlayerRepository, VideoRepository
from fap.scouting.service import ScoutingService
from fap.ui.builtin import video_sync as VS
from fap.workspaces.audit import AuditService
from fap.workspaces.repositories import AuditRepository


# ================================================================ pure calculation
@pytest.mark.parametrize("offset,minute,second,expected", [
    (10.0, 2, 30, 160.0),          # 10 + 120 + 30
    (0.0, 0, 0, 0.0),
    (5.5, "3", "15", 200.5),       # string coercion
    (5.0, None, None, 5.0),        # missing -> 0
    (-100.0, 1, 0, 0.0),           # clamped, never negative
    (float("nan"), 1, 0, 60.0),    # NaN offset -> 0
])
def test_event_video_time(offset, minute, second, expected):
    assert VS.event_video_time(offset, minute, second) == expected


# ================================================================ provider detection
@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://hudl.com/video/123", None),
    ("", None),
])
def test_youtube_id(url, expected):
    assert VS.youtube_id(url) == expected


@pytest.mark.parametrize("url,expected", [
    ("https://vimeo.com/123456789", "123456789"),
    ("https://player.vimeo.com/video/123456789", "123456789"),
    ("https://vimeo.com/channels/staffpicks/123456789", "123456789"),
    ("https://www.youtube.com/watch?v=x", None),
])
def test_vimeo_id(url, expected):
    assert VS.vimeo_id(url) == expected


def test_component_mode_and_seekable():
    assert VS.component_mode(PlayerVideo(id="1", player_id="p", kind="upload")) == "upload"
    assert VS.component_mode(PlayerVideo(id="2", player_id="p", kind="external",
                                         url="https://youtu.be/dQw4w9WgXcQ")) == "youtube"
    assert VS.component_mode(PlayerVideo(id="3", player_id="p", kind="external",
                                         url="https://vimeo.com/123")) == "vimeo"
    # Hudl / SkillCorner / plain URLs are NOT seekable -> left as today
    hudl = PlayerVideo(id="4", player_id="p", kind="external", provider="hudl",
                       url="https://www.hudl.com/video/abc")
    assert VS.component_mode(hudl) is None and VS.is_seekable(hudl) is False


# ================================================================ trust boundary
def test_parse_result_accepts_valid_mark():
    out = VS.parse_result({"action": "mark", "time": 12.5, "nonce": "abc"})
    assert out == {"action": "mark", "time": 12.5, "nonce": "abc"}
    assert VS.parse_result({"action": "mark", "time": 0})["nonce"] == ""


@pytest.mark.parametrize("value", [
    None, {}, [], "x", {"action": "seek", "time": 1},
    {"action": "mark"}, {"action": "mark", "time": -1},
    {"action": "mark", "time": "5"}, {"action": "mark", "time": True},
])
def test_parse_result_rejects_bad_values(value):
    assert VS.parse_result(value) is None


# ================================================================ backward-compat state
def test_new_video_defaults_to_render_as_today():
    v = PlayerVideo(id="x", player_id="p", kind="external",
                    url="https://youtu.be/dQw4w9WgXcQ")
    # even though the source is seekable, an un-synced video has no match/offset ...
    assert v.match_id == "" and v.sync_offset_seconds is None
    # ... which is exactly the condition the Videos tab uses to render it unchanged.
    renders_as_today = (VS.component_mode(v) is None) or (not v.match_id) \
        or (v.sync_offset_seconds is None)
    assert renders_as_today is True


# ================================================================ migration + persistence
def test_migration_12_adds_sync_columns(tmp_path):
    db = Database(tmp_path / "m.sqlite3")
    try:
        assert db.schema_version() >= 12
        cols = {r["name"] for r in db.query("PRAGMA table_info(player_videos)")}
        assert {"match_id", "sync_offset_seconds"} <= cols
    finally:
        db.close()


def test_repository_round_trips_new_fields(tmp_path):
    db = Database(tmp_path / "r.sqlite3")
    try:
        PlayerRepository(db).save(Player(id="p1", name="X"))
        vr = VideoRepository(db)
        vr.add(PlayerVideo(id="v1", player_id="p1", kind="external", provider="youtube",
                           url="https://youtu.be/dQw4w9WgXcQ", title="clip"))
        # a freshly-added video is un-synced (renders as today)
        v = vr.get("v1")
        assert v.match_id == "" and v.sync_offset_seconds is None
        # set + read back
        vr.set_sync("v1", "M1", 12.5)
        v = vr.get("v1")
        assert v.match_id == "M1" and v.sync_offset_seconds == 12.5
        # clearing back to un-synced
        vr.set_sync("v1", "", None)
        v = vr.get("v1")
        assert v.match_id == "" and v.sync_offset_seconds is None
    finally:
        db.close()


class _AllowAll:
    def require(self, user, cap, scope=None): pass
    def can(self, user, cap, scope=None): return True


def test_service_set_video_sync(tmp_path):
    db = Database(tmp_path / "s.sqlite3")
    try:
        PlayerRepository(db).save(Player(id="p1", name="X"))
        VideoRepository(db).add(PlayerVideo(id="v1", player_id="p1", kind="external",
                                            provider="youtube",
                                            url="https://youtu.be/dQw4w9WgXcQ", title="clip"))
        svc = ScoutingService(db, permissions=_AllowAll(),
                              audit=AuditService(AuditRepository(db)))
        user = User(email="a@club.com", name="A", role=Role.SUPER_ADMIN, provider_id="dev")

        out = svc.set_video_sync(user, "v1", "M1", 12.5)
        assert out is not None and out.match_id == "M1" and out.sync_offset_seconds == 12.5

        cleared = svc.set_video_sync(user, "v1", "", None)
        assert cleared.match_id == "" and cleared.sync_offset_seconds is None

        assert svc.set_video_sync(user, "does-not-exist", "M2", 1.0) is None
    finally:
        db.close()
