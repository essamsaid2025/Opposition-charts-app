"""Unified operational-id scheme: academy ACD-, club CLB-, scouting SCT- (all unique).

Locks the additive ``scouting``/``SCT`` player type alongside the existing club/academy/trialist
ones, so every player added under any pathway gets a stable, unique, human-readable id.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from fap.scouting import identity as I


def test_prefixes_for_each_pathway():
    assert I.format_operational_id("academy", 1) == "ACD-000001"
    assert I.format_operational_id("first_team", 1) == "CLB-000001"
    assert I.format_operational_id("scouting", 1) == "SCT-000001"
    assert I.format_operational_id("trialist", 1) == "TRI-000001"


def test_scouting_type_is_registered_and_normalised():
    assert "scouting" in I.PLAYER_TYPES
    assert I.TYPE_PREFIX["scouting"] == "SCT"
    assert I.normalize_player_type("scout") == "scouting"
    assert I.normalize_player_type("scouting") == "scouting"
    assert I.type_label("scouting") == "Scouting"


def test_ids_are_unique_across_pathways():
    ids = {I.format_operational_id(t, n)
           for t in ("academy", "first_team", "scouting", "trialist") for n in range(1, 4)}
    assert len(ids) == 12                              # prefix+number is globally unique
