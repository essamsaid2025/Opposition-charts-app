"""Pass-network / average-position player nodes: show the on-pitch XI (not subs),
each dot carrying its shirt number. StatsBomb keeps jersey numbers only in the
Starting XI lineup, so the adapter backfills them; the network/shape trim to the 11
most-involved players; and the marker never prints a non-numeric label.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import pandas as pd

from fap.visuals import analysis as A


# ================================================================ helpers
def test_top_players_keeps_most_involved():
    df = pd.DataFrame({"player": list("abcdefghijklm"),
                       "count": [13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]})
    top = A.top_players(df, 11)
    assert len(top) == 11 and "l" not in set(top["player"]) and "m" not in set(top["player"])


def test_first_number_skips_leading_nan():
    assert A._first_number(pd.Series([np.nan, np.nan, 7, 9])) == 7
    assert pd.isna(A._first_number(pd.Series([np.nan, np.nan])))
    assert pd.isna(A._first_number(pd.Series(["", "nan"])))


# ================================================================ StatsBomb jersey backfill
def test_statsbomb_backfills_jersey_from_lineup():
    from fap.pipeline.statsbomb_csv import reshape
    lineup = ("[{'player': {'id': 1, 'name': 'Alpha'}, 'jersey_number': 9}, "
              "{'player': {'id': 2, 'name': 'Beta'}, 'jersey_number': 4}]")
    df = pd.DataFrame({
        "type.name": ["Starting XI", "Pass", "Pass"],
        "location": ["", "[60, 40]", "[50, 30]"],
        "player.name": ["", "Alpha", "Beta"],
        "team.name": ["T", "T", "T"],
        "tactics.lineup": [lineup, "", ""]})
    out = reshape(df)
    assert out.loc[out["player"] == "Alpha", "jersey_number"].iloc[0] == 9
    assert out.loc[out["player"] == "Beta", "jersey_number"].iloc[0] == 4


def test_statsbomb_receiver_is_name_not_id():
    # the receiver must be the recipient NAME (matches player), so network edges join
    from fap.pipeline.statsbomb_csv import reshape
    df = pd.DataFrame({
        "type.name": ["Pass"], "location": ["[60, 40]"], "player.name": ["Alpha"],
        "team.name": ["T"], "pass.recipient.name": ["Beta"], "pass.recipient.id": [999]})
    out = reshape(df)
    assert out["receiver"].iloc[0] == "Beta"


def test_pass_network_draws_edges_when_receiver_is_name():
    # names on both sides -> the ring produces real edges (regression for the
    # 'no network lines' bug caused by receiver holding ids)
    starters = [f"p{i}" for i in range(11)]
    rows = []
    for i, pl in enumerate(starters):
        rec = starters[(i + 1) % 11]
        for _ in range(3):
            rows.append({"event_type": "pass", "player": pl, "receiver": rec,
                         "outcome": "successful", "x": 50, "y": 50, "end_x": 55,
                         "end_y": 50, "jersey_number": i + 1})
    _, edges = A.pass_network(pd.DataFrame(rows), min_links=2, max_players=11)
    assert len(edges) == 11 and (edges["count"] >= 2).all()


# ================================================================ network trims to XI
def test_pass_network_caps_to_eleven_with_numbers():
    starters = [f"p{i}" for i in range(11)]
    rows = []
    for i, pl in enumerate(starters):
        rec = starters[(i + 1) % 11]
        for _ in range(3):                              # a passing ring, 3 links each
            rows.append({"event_type": "pass", "player": pl, "receiver": rec,
                         "outcome": "successful", "x": 50, "y": 50, "end_x": 55,
                         "end_y": 50, "jersey_number": i + 1})
    rows.append({"event_type": "pass", "player": "sub", "receiver": "p0",
                 "outcome": "successful", "x": 50, "y": 50, "end_x": 55, "end_y": 50,
                 "jersey_number": 99})                   # a low-involvement substitute
    nodes, edges = A.pass_network(pd.DataFrame(rows), min_links=1, max_players=11)
    assert len(nodes) == 11 and "sub" not in set(nodes["player"])         # subs dropped
    assert set(edges["p1"]) <= set(nodes["player"])                       # no dangling edges
    assert set(edges["p2"]) <= set(nodes["player"])
    assert int(pd.to_numeric(nodes["jersey_number"], errors="coerce").notna().sum()) == 11


# ================================================================ marker never prints NA
def test_player_markers_skips_non_numeric():
    from fap.visuals.context import LayerContext
    from fap.visuals.layers.base import layer_registry
    from fap.visuals.legend import LegendEngine
    from fap.visuals.pitch import get_spec
    from fap.visuals.tokens import StyleTokens
    from fap.themes.theme import ThemeManager
    from matplotlib.figure import Figure
    theme = ThemeManager("assets/themes").get("opta_dark")
    df = pd.DataFrame({"x": [40, 60], "y": [40, 50], "jersey_number": [7, np.nan]})
    fig = Figure(); ax = fig.add_subplot(111)
    ctx = LayerContext(fig=fig, ax=ax, df=df, theme=theme,
                       tokens=StyleTokens.from_theme(theme), controls={},
                       pitch_spec=get_spec("uefa"), legend=LegendEngine())
    layer_registry.create("player_markers", df=df).draw(ctx)
    texts = [t.get_text() for t in ax.texts]
    assert "7" in texts                                   # the real number is drawn
    assert not any(t.lower() in ("nan", "<na>", "na") for t in texts)   # NaN skipped
