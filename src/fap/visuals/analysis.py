"""Shared football-analysis selectors and metrics used by the visualization
library. Pure functions over the canonical event model - the single place
football semantics live, so plugins stay declarative and nothing duplicates.

Definitions follow common industry conventions (progressive = ≥25% closer to
goal or ≥10 canonical units; switch = ≥40 lateral units; zone 14 / half-space
boundaries on the canonical 0-100 grid; xT = Karun Singh's published 12x8
grid)."""
from __future__ import annotations

import numpy as np
import pandas as pd

_SUCCESS = ("successful", "success", "complete", "won")

# ------------------------------------------------------------------ selectors
def passes(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["event_type"].str.lower().eq("pass")]

def carries(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["event_type"].str.lower().isin(["carry", "dribble"])]

def shots(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["event_type"].str.lower().eq("shot")]

def crosses(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["event_type"].str.lower().eq("cross")]

def movement(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["event_type"].str.lower().isin(["pass", "carry", "dribble", "cross"])]

def defensive(df: pd.DataFrame, kinds: tuple[str, ...] = ()) -> pd.DataFrame:
    kinds = kinds or ("duel", "recovery", "interception", "clearance",
                      "tackle", "block", "pressure")
    return df[df["event_type"].str.lower().isin(kinds)]

def successful(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["outcome"].str.lower().isin(_SUCCESS)]

def unsuccessful(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df["outcome"].str.lower().isin(_SUCCESS) & df["outcome"].ne("")]

def goalkeeper(df: pd.DataFrame) -> pd.DataFrame:
    gk_events = df["event_type"].str.lower().isin(
        ["save", "claim", "punch", "smother", "keeper sweeper", "goalkeeper"])
    gk_pos = df["position"].str.lower().str.contains("goalkeeper|^gk$", regex=True, na=False)
    return df[gk_events | gk_pos]

# ------------------------------------------------------------------ pass flags
def forward(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["end_x"] - df["x"]) > 8]

def backward(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["end_x"] - df["x"]) < -8]

def sideways(df: pd.DataFrame) -> pd.DataFrame:
    dx = df["end_x"] - df["x"]
    return df[dx.abs() <= 8]

def progressive(df: pd.DataFrame) -> pd.DataFrame:
    """≥25% closer to the opponent goal (min 10 units gained)."""
    dist0 = 100 - df["x"]
    dist1 = 100 - df["end_x"]
    gain = dist0 - dist1
    return df[(gain >= 0.25 * dist0) & (gain >= 10)]

def line_breaking(df: pd.DataFrame) -> pd.DataFrame:
    """Forward passes through the central corridor gaining ≥15 units -
    an honest event-data proxy for breaking an opposition line."""
    central = df["y"].between(20, 80) & df["end_y"].between(15, 85)
    return df[((df["end_x"] - df["x"]) >= 15) & central]

def vertical(df: pd.DataFrame) -> pd.DataFrame:
    dx = (df["end_x"] - df["x"]).abs()
    dy = (df["end_y"] - df["y"]).abs()
    return df[(df["end_x"] > df["x"]) & (dx >= 12) & (dy <= dx * 0.5)]

def switches(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["end_y"] - df["y"]).abs() >= 40]

def long_passes(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["pass_length"].fillna(0) >= 30]

def short_passes(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["pass_length"].fillna(0).between(0.1, 15)]

def key_passes(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["key_pass"].astype(bool)]

def assists(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["assist"].astype(bool)]

def under_pressure(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["under_pressure"].astype(bool)]

# ------------------------------------------------------------------ zones
ZONE_14 = (66.67, 33.33, 83.0, 66.67)                       # x0, y0, x1, y1
HALF_SPACES = ((50.0, 15.0, 100.0, 33.33), (50.0, 66.67, 100.0, 85.0))
PENALTY_AREA = (83.0, 21.0, 100.0, 79.0)
FINAL_THIRD = (66.67, 0.0, 100.0, 100.0)
WIDE_AREAS = ((0.0, 0.0, 100.0, 15.0), (0.0, 85.0, 100.0, 100.0))
CROSSING_ZONES = ((66.67, 0.0, 100.0, 21.0), (66.67, 79.0, 100.0, 100.0))
GOLDEN_ZONE = (88.0, 30.0, 100.0, 70.0)

def in_zone(x: pd.Series, y: pd.Series, zone: tuple[float, float, float, float]) -> pd.Series:
    x0, y0, x1, y1 = zone
    return x.between(x0, x1) & y.between(y0, y1)

def entries_into(df: pd.DataFrame, zone: tuple[float, float, float, float]) -> pd.DataFrame:
    """Movement events starting outside a zone and ending inside it."""
    d = movement(df)
    return d[~in_zone(d["x"], d["y"], zone) & in_zone(d["end_x"], d["end_y"], zone)]

# ------------------------------------------------------------------ expected threat
# Karun Singh's published xT grid (12 columns x 8 rows), attacking left->right.
XT_GRID = np.array([
 [0.0060,0.0079,0.0088,0.0098,0.0106,0.0115,0.0135,0.0166,0.0221,0.0298,0.0402,0.0623],
 [0.0072,0.0086,0.0094,0.0105,0.0115,0.0136,0.0159,0.0201,0.0283,0.0417,0.0629,0.0954],
 [0.0077,0.0093,0.0101,0.0110,0.0121,0.0143,0.0176,0.0233,0.0349,0.0568,0.0886,0.1477],
 [0.0081,0.0097,0.0106,0.0116,0.0129,0.0148,0.0193,0.0272,0.0433,0.0741,0.1231,0.2223],
 [0.0081,0.0097,0.0106,0.0116,0.0129,0.0148,0.0193,0.0272,0.0433,0.0741,0.1231,0.2223],
 [0.0077,0.0093,0.0101,0.0110,0.0121,0.0143,0.0176,0.0233,0.0349,0.0568,0.0886,0.1477],
 [0.0072,0.0086,0.0094,0.0105,0.0115,0.0136,0.0159,0.0201,0.0283,0.0417,0.0629,0.0954],
 [0.0060,0.0079,0.0088,0.0098,0.0106,0.0115,0.0135,0.0166,0.0221,0.0298,0.0402,0.0623],
])

def xt_value(x: pd.Series, y: pd.Series) -> np.ndarray:
    col = np.clip((np.asarray(x, dtype=float) / 100 * 12).astype(int), 0, 11)
    row = np.clip((np.asarray(y, dtype=float) / 100 * 8).astype(int), 0, 7)
    return XT_GRID[row, col]

def xt_gain(df: pd.DataFrame) -> pd.Series:
    d = df.dropna(subset=["x", "y", "end_x", "end_y"])
    gain = xt_value(d["end_x"], d["end_y"]) - xt_value(d["x"], d["y"])
    return pd.Series(gain, index=d.index)

# ------------------------------------------------------------------ networks
def pass_network(df: pd.DataFrame, *, min_links: int = 2
                 ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Nodes (player avg position + volume) and edges (pair counts) from
    successful passes with a known receiver."""
    d = successful(passes(df))
    d = d[d["player"].str.strip().ne("") & d["receiver"].str.strip().ne("")]
    nodes = d.groupby("player").agg(
        x=("x", "mean"), y=("y", "mean"), count=("x", "size"),
        jersey_number=("jersey_number", "first")).reset_index()
    pair = d.assign(pair=[tuple(sorted(t)) for t in zip(d["player"], d["receiver"])])
    edges = pair.groupby("pair").size().reset_index(name="count")
    edges = edges[edges["count"] >= min_links]
    edges[["p1", "p2"]] = pd.DataFrame(edges["pair"].tolist(), index=edges.index)
    return nodes, edges.drop(columns=["pair"])

# ------------------------------------------------------------------ sequences & transitions
def sequences(df: pd.DataFrame) -> pd.api.typing.DataFrameGroupBy:
    d = df[df["sequence_id"].astype(str).str.strip().ne("")]
    return d.groupby(d["sequence_id"].astype(str), sort=False)

def sequence_reaching(df: pd.DataFrame, x_target: float = 66.67,
                      within_seconds: float | None = None) -> pd.DataFrame:
    """Rows of sequences that reach x_target (optionally within N seconds of
    the sequence start) - the basis for fast attacks / counter attacks."""
    keep: list[str] = []
    for seq_id, g in sequences(df):
        reached = g[g[["x", "end_x"]].max(axis=1) >= x_target]
        if reached.empty:
            continue
        if within_seconds is not None:
            start = g["time_min"].min()
            if (reached["time_min"].min() - start) * 60 > within_seconds:
                continue
        keep.append(seq_id)
    d = df[df["sequence_id"].astype(str).isin(keep)]
    return d

def turnovers(df: pd.DataFrame) -> pd.DataFrame:
    """Possession-ending failures: unsuccessful passes/carries + dispossessions."""
    lost = unsuccessful(movement(df))
    disp = df[df["event_type"].str.lower().isin(["dispossessed", "error", "miscontrol"])]
    return pd.concat([lost, disp]).sort_index()

def counterpress_window(df: pd.DataFrame, seconds: float = 6.0) -> pd.DataFrame:
    """Defensive actions within N seconds after a turnover by the same team -
    an event-data counter-pressing proxy."""
    losses = turnovers(df)
    if losses.empty:
        return df.iloc[0:0]
    d = defensive(df)
    keep = pd.Series(False, index=d.index)
    for _, loss in losses.iterrows():
        window = (d["match_id"].astype(str).eq(str(loss["match_id"]))
                  & (d["time_min"] >= loss["time_min"])
                  & (d["time_min"] <= loss["time_min"] + seconds / 60))
        keep |= window
    return d[keep]
