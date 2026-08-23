"""FAP visualization semantic audit — golden-data proof that every event map
plots exactly the events its name claims (positive AND negative), that coordinates
are preserved canonically, and that Set Piece is a Data Hub consumer.

Golden data lives in ``sample_data/audit/`` (downloadable, human-readable). This
suite ingests it through the REAL pipeline and asserts exact event-id populations
per canonical selector, so a regression that widens/narrows any selector fails here.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
import pytest

from fap.pipeline.pipeline import DataPipeline
from fap.pipeline import transforms
from fap.providers.base import RawDataset
from fap.setpieces.derivation import _classify, derive_set_pieces
from fap.visuals import analysis as A

_AUDIT = pathlib.Path(__file__).resolve().parent.parent / "sample_data" / "audit"


def _load(name: str) -> pd.DataFrame:
    raw = pd.read_csv(_AUDIT / name)
    return DataPipeline().run(RawDataset(frame=raw))


def _ids(d) -> set:
    return set(d["event_id"].tolist())


@pytest.fixture(scope="module")
def df():
    return _load("fap_visualization_audit_events.csv")


# ============================================================ passing (exact sets)
def test_pass_map_is_exactly_passes(df):
    assert _ids(A.passes(df)) == {"P001", "P002", "P003", "P004", "P005", "K040",
                                  "FT060", "FT061", "PA070", "PA071"}


def test_progressive_passes_are_only_progressive(df):
    prog = _ids(A.progressive(A.passes(df)))
    assert prog == {"P001", "P004", "K040", "FT060", "FT061", "PA070"}
    # NEGATIVE: non-progressive passes must NOT appear
    assert {"P002", "P003", "P005", "PA071"}.isdisjoint(prog)


def test_direction_selectors(df):
    assert _ids(A.forward(A.passes(df))) == {"P001", "P004", "K040", "FT060", "FT061", "PA070"}
    assert _ids(A.backward(A.passes(df))) == {"P003"}
    assert _ids(A.sideways(A.passes(df))) == {"P002", "P005", "PA071"}


def test_key_passes_are_only_flagged(df):
    # regression for the NaN-boolean bug: only the row flagged key_pass=1 qualifies
    assert _ids(A.key_passes(A.passes(df))) == {"K040"}


def test_crosses_are_only_crosses(df):
    assert _ids(A.crosses(df)) == {"X030"}


# ============================================================ carrying (exact sets)
def test_carry_map_and_progressive_carries(df):
    assert _ids(A.carries(df)) == {"C010", "C011"}
    prog = _ids(A.progressive(A.carries(df)))
    assert prog == {"C010"}
    assert "C011" not in prog                                # NEGATIVE


# ============================================================ shooting (exact sets)
def test_shot_map_is_only_shots_no_passes(df):
    shots = _ids(A.shots(df))
    assert shots == {"S020", "S021", "S022", "SPS001"}
    # NEGATIVE: passes/carries/defensive must never appear on a shot map
    assert shots.isdisjoint({"P001", "C010", "D050", "X030"})


def test_goal_map_is_only_goals(df):
    goals = _ids(A.shots(df)[A.shots(df)["shot_result"].str.lower().eq("goal")])
    assert goals == {"S021"}
    assert "S020" not in goals and "S022" not in goals       # saved/off-target excluded


# ============================================================ defensive (exact sets)
@pytest.mark.parametrize("kind,expected", [
    ("interception", {"D050"}), ("recovery", {"D051"}), ("tackle", {"D052"}),
    ("pressure", {"D053"}), ("clearance", {"D054"}), ("block", {"D056"})])
def test_specific_defensive_maps_are_exact(df, kind, expected):
    got = _ids(A.defensive(df, (kind,)))
    assert got == expected
    # NEGATIVE: a specific defensive map must not contain other defensive kinds
    others = {"D050", "D051", "D052", "D053", "D054", "D056"} - expected
    assert got.isdisjoint(others)


def test_defensive_actions_is_the_union(df):
    assert _ids(A.defensive(df)) == {"D050", "D051", "D052", "D053", "D054", "D055", "D056"}


# ============================================================ zones (entry semantics)
def test_final_third_entries_use_start_outside_end_inside(df):
    entries = _ids(A.entries_into(df, A.FINAL_THIRD))
    assert entries == {"P001", "P004", "C010", "FT060"}
    assert "FT061" not in entries        # NEGATIVE: already inside the final third


def test_penalty_area_entries(df):
    entries = _ids(A.entries_into(df, A.PENALTY_AREA))
    assert entries == {"P004", "K040", "FT061", "PA070", "X030"}
    assert "PA071" not in entries        # NEGATIVE: starts and ends inside the box


# ============================================================ coordinates
def test_coordinates_are_preserved_canonically(df):
    p = df[df["event_id"] == "P001"].iloc[0]
    assert (p["x"], p["y"], p["end_x"], p["end_y"]) == (20, 50, 70, 50)
    s = df[df["event_id"] == "S021"].iloc[0]
    assert (s["x"], s["y"]) == (90, 45)      # shot uses shot location, not end


def test_attack_direction_flip_is_a_pure_coordinate_transform(df):
    flipped = transforms.flip_left_to_right(df.copy())
    p = flipped[flipped["event_id"] == "P001"].iloc[0]
    assert p["x"] == 80 and p["end_x"] == 30      # x -> 100 - x, event population unchanged
    assert _ids(A.passes(flipped)) == _ids(A.passes(df))


# ============================================================ scope
def test_player_scope_does_not_leak_other_players(df):
    a6 = df[df["player"] == "A6"]
    assert _ids(A.shots(a6)) == {"S020", "S021"}          # only A6's shots
    b3 = df[df["player"] == "B3"]
    assert _ids(A.shots(b3)) == {"S022"}                  # B3's, not A6's


def test_team_scope(df):
    team_a = df[df["team"] == "Team A"]
    assert _ids(A.shots(team_a)) == {"S020", "S021", "SPS001"}
    assert "S022" not in _ids(A.shots(team_a))            # Team B shot excluded


# ============================================================ set pieces (separation)
def _by_type(frame):
    keys = {"corner", "free_kick", "throw_in", "penalty",
            "corner_kick", "free-kick", "freekick", "throw-in", "throwin", "throw in",
            "penalty_kick", "direct_free_kick", "from corner", "from free kick", "from throw in"}
    sub = frame[frame["event_type"].astype(str).str.lower().isin(keys)
                | frame["set_piece"].astype(str).str.lower().isin(keys)]
    out: dict[str, set] = {}
    for _, r in sub.iterrows():
        t = _classify(r.to_dict())
        out.setdefault(t, set()).add(r["event_id"])
    return out


def test_corner_map_contains_only_corners_events_file(df):
    by = _by_type(df)
    assert by["corner"] == {"SPC001", "SPC002", "SPS001"}
    assert by["free_kick"] == {"SPFK001"}
    # NEGATIVE separations
    assert "SPFK001" not in by["corner"]
    assert "SPC001" not in by["free_kick"]
    assert "SPTI001" not in by["corner"] and "SPTI001" not in by["free_kick"]


def test_set_pieces_file_classification():
    frame = _load("fap_visualization_audit_set_pieces.csv")
    by = _by_type(frame)
    assert by["corner"] == {"CRN001", "CRN002", "SPSHOT001"}
    assert by["free_kick"] == {"FK001", "FK002"}
    assert by["throw_in"] == {"TI001"}
    assert by["penalty"] == {"PEN001"}
    # NORMALSHOT001 is a plain shot, not a set piece
    assert "NORMALSHOT001" not in {i for s in by.values() for i in s}


def test_derive_set_pieces_produces_expected_records():
    frame = _load("fap_visualization_audit_set_pieces.csv")
    sps = derive_set_pieces(frame)
    corners = [sp for sp in sps if sp.type == "corner"]
    fks = [sp for sp in sps if sp.type == "free_kick"]
    assert len(corners) == 3 and len(fks) == 2
    # coordinates come from the source event, not fabricated
    c1 = next(sp for sp in sps if sp.start_x == 100 and sp.start_y == 100)
    assert c1.type == "corner"
