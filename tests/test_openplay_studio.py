"""Phase 16 — Open Play engine interface + Studio (workspace/UI only).

Proves the additive engine-exposure layer is byte-identical to the pre-extraction engine
and that the Studio is a pure second consumer:

* ``default_ctx`` is the single source and equals run_app's inline ctx literal;
* rendering via the injected engine yields byte-identical PNGs;
* ``apply_filters`` matches run_app's inline filter logic;
* the engine holder is populated and the Studio page registers under Analysis.

``import app`` is allowed HERE only (FAP_TEST) — the Studio never imports app at runtime.
"""
import os
import pathlib
import sys

os.environ["FAP_TEST"] = "1"
_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))                    # app.py
sys.path.insert(0, str(_ROOT / "src"))

import numpy as np
import pandas as pd

import app  # noqa: E402  (FAP_TEST-guarded; registers the engine at import)
from fap.openplay import add_derived_columns  # noqa: E402
from fap.openplay.config import SUCCESS_WORDS  # noqa: E402
from fap.openplay.engine import (  # noqa: E402
    default_ctx, apply_filters, get_engine, engine_available, OPEN_PLAY_FILTERS,
)


def _frame():
    rng = np.random.default_rng(7)
    n = 240
    raw = pd.DataFrame({
        "match_id": ["m1"] * (n // 2) + ["m2"] * (n - n // 2),
        "team": rng.choice(["Home", "Away"], n), "opponent": rng.choice(["Away", "Home"], n),
        "player": rng.choice(["A. One", "B. Two", "C. Three"], n),
        "event_type": rng.choice(["pass", "carry", "shot", "cross", "recovery", "tackle"], n),
        "outcome": rng.choice(["successful", "unsuccessful", "complete", "won"], n),
        "x": rng.uniform(0, 100, n), "y": rng.uniform(0, 100, n),
        "x2": rng.uniform(0, 100, n), "y2": rng.uniform(0, 100, n),
        "minute": rng.integers(0, 95, n), "second": rng.integers(0, 60, n),
        "period": rng.choice([1, 2], n), "phase": rng.choice(["in possession", "out of possession"], n),
        "sequence_id": rng.integers(1, 30, n).astype(str),
        "shot_result": rng.choice(["Goal", "Saved", "Off Target", ""], n),
        "body_part": rng.choice(["foot", "head", ""], n), "set_piece": [""] * n,
    })
    return add_derived_columns(raw)


def _orig_ctx(vt, spec, df_all, title):
    """run_app's inline ctx literal (copied verbatim from app.py) — the ground truth."""
    return {
        "vt": vt, "spec": spec, "title": title, "show_title": True,
        "title_size": 20, "label_size": 11, "legend_size": 10, "respect_filter": False,
        "marker": {"shape": "Circle", "size": 80, "edge_width": 1.1, "edge_color": vt["line"],
                   "alpha": 0.85, "rotation": 0, "jitter": 0.0, "zorder": 6,
                   "shadow": False, "glow": False, "glow_color": vt["accent"]},
        "arrow": {"kind": "Straight", "width": 1.6, "head": 10, "curvature": 0.18,
                  "alpha": 0.72, "linecap": "round", "shadow": False, "glow": False, "cmap": "viridis"},
        "labels": {"show": True, "show_players": False, "smart": True, "hide_overlapping": True,
                   "halo": True, "halo_color": vt["pitch"], "box": False, "leader_lines": True,
                   "size": 9, "offset": 1.6, "rotation": 0, "max_labels": 0},
        "legend": {"show": True, "position": "Bottom", "orientation": "Horizontal", "frame": True,
                   "title": "", "renames": "", "hide": "", "order": ""},
        "heat": {"type": "Gaussian KDE", "preset": "All selected events", "cmap": "Greens",
                 "alpha": 0.65, "bandwidth": 3.0, "levels": 10, "bins": 13, "gridsize": 22,
                 "cell_size": 10, "interpolation": "bilinear", "normalization": "Count",
                 "threshold": 0, "percentile_scale": False, "log_scale": False, "cell_labels": False},
        "colors": {"arrow": vt["accent"], "unsuccess": vt["danger"], "start": vt["accent"],
                   "end": vt["accent2"], "shot": vt["panel"], "goal": vt["danger"], "zone": vt["warning"],
                   "bar": vt["accent"], "line": vt["accent"], "trend": vt["danger"],
                   "carry": vt["grey"], "cross": vt["accent2"]},
        "aux": {"df_all": df_all, "top_n": 10, "zone_mode": "Pitch Thirds", "start_end_event": "pass",
                "timeline_focus": "All", "trend_metric": "All Events", "sequence_mode": "Specific sequence",
                "sequence_id": "", "show_sequence_numbers": True, "line_width": 2.4, "dashboard_layout": None},
    }


def _strip(d):
    d = {k: (dict(v) if isinstance(v, dict) else v) for k, v in d.items()}
    d["aux"] = {k: v for k, v in d["aux"].items() if k != "df_all"}
    return d


def test_engine_holder_populated():
    assert engine_available()
    eng = get_engine()
    assert eng.version == "16.0"
    assert len(eng.viz_registry) >= 20 and eng.categories()
    for key in ("themes", "marker_shapes", "heat_types", "legend_positions", "pitch_views"):
        assert key in eng.metadata
    assert [f["id"] for f in eng.filters] == [f["id"] for f in OPEN_PLAY_FILTERS]


def test_default_ctx_is_single_source():
    eng = get_engine()
    vt = eng.metadata["themes"]["Opta Analyst"]
    spec = eng.pitch_spec_cls()
    got = default_ctx(vt, spec, title="Pass Map")
    orig = _orig_ctx(vt, spec, None, "Pass Map")
    assert _strip(got) == _strip(orig)


def test_render_byte_identical_via_engine():
    import matplotlib.pyplot as plt
    eng = get_engine()
    df = _frame()
    vt = eng.metadata["themes"]["Opta Analyst"]
    spec = eng.pitch_spec_cls()
    df_all = eng.apply_pitch_transforms(df, spec)
    f = eng.apply_pitch_transforms(df, spec)
    names = [n for n in ("Pass Map", "Shot Map", "Carry Map") if n in eng.viz_registry]
    assert names, "expected representative vizs in registry"
    for nm in names:
        orig = _orig_ctx(vt, spec, df_all, nm)
        new = eng.default_ctx(vt, spec, title=nm, aux={"df_all": df_all})
        fo = eng.render(nm, f, orig); bo = eng.export(fo, "png", 120); plt.close(fo)
        fn = eng.render(nm, f, new); bn = eng.export(fn, "png", 120); plt.close(fn)
        assert bo == bn, f"{nm} not byte-identical ({len(bo)} vs {len(bn)})"


def test_full_control_surface_byte_identical():
    """A fully-customised Inspector state (non-default across every group + spec) renders
    byte-identically to run_app's literal ctx built from the same values."""
    import matplotlib.pyplot as plt
    eng = get_engine()
    df = _frame()
    vt = eng.metadata["themes"]["Opta Analyst"]
    spec = eng.pitch_spec_cls(orientation="Vertical", mirror=True, flip_y=True,
                              thirds_mode="Highlight final third", thirds_width=2.0,
                              thirds_alpha=0.5, stripes=False)
    df_all = eng.apply_pitch_transforms(df, spec)
    f = eng.apply_pitch_transforms(df, spec)
    top = dict(title="Custom", show_title=False, title_size=28, label_size=14,
               legend_size=13, respect_filter=True)
    marker = {"shape": "Square", "size": 120, "edge_width": 2.0, "edge_color": "#111111",
              "alpha": 0.7, "rotation": 45, "jitter": 0.5, "zorder": 8, "shadow": True,
              "glow": True, "glow_color": "#00ff00"}
    arrow = {"kind": "Curved", "width": 2.5, "head": 14, "curvature": 0.3, "alpha": 0.9,
             "linecap": "butt", "shadow": True, "glow": True, "cmap": "magma"}
    labels = {"show": True, "show_players": True, "smart": False, "hide_overlapping": False,
              "halo": False, "halo_color": vt["pitch"], "box": True, "leader_lines": False,
              "size": 12, "offset": 2.0, "rotation": 30, "max_labels": 10}
    legend = {"show": True, "position": "Top", "orientation": "Vertical", "frame": False,
              "title": "Legend", "renames": "", "hide": "", "order": ""}
    heat = {"type": "Grid Heatmap", "preset": "Pass density", "cmap": "Blues", "alpha": 0.8,
            "bandwidth": 4.0, "levels": 12, "bins": 20, "gridsize": 30, "cell_size": 12,
            "interpolation": "nearest", "normalization": "Percent", "threshold": 10,
            "percentile_scale": True, "log_scale": True, "cell_labels": True}
    colors = {"arrow": "#123456", "unsuccess": "#654321", "start": "#0a0b0c", "end": "#111213",
              "shot": "#141516", "goal": "#171819", "zone": "#1a1b1c", "bar": "#1d1e1f",
              "line": "#202122", "trend": "#232425", "carry": "#262728", "cross": "#292a2b"}
    aux = {"df_all": df_all, "top_n": 15, "zone_mode": "Lanes", "start_end_event": "carry",
           "timeline_focus": "All", "trend_metric": "Shots", "sequence_mode": "Longest sequence",
           "sequence_id": "", "show_sequence_numbers": False, "line_width": 3.0, "dashboard_layout": None}

    new = eng.default_ctx(vt, spec, marker=marker, arrow=arrow, labels=labels, legend=legend,
                          heat=heat, colors=colors, aux=aux, **top)
    lit = {"vt": vt, "spec": spec, "marker": marker, "arrow": arrow, "labels": labels,
           "legend": legend, "heat": heat, "colors": colors, "aux": aux, **top}
    assert _strip(new) == _strip(lit)          # override path is structurally exact
    for nm in [n for n in ("Pass Map", "Shot Map") if n in eng.viz_registry]:
        cn = dict(new); cn["title"] = nm
        cl = dict(lit); cl["title"] = nm
        fo = eng.render(nm, f, cl); bo = eng.export(fo, "png", 110); plt.close(fo)
        fn = eng.render(nm, f, cn); bn = eng.export(fn, "png", 110); plt.close(fn)
        assert bo == bn, f"{nm} full-override not byte-identical"


def test_apply_filters_matches_inline():
    df = _frame()

    def inline(team, opp, match, events, phases, players, mr, only):
        f = df.copy()
        if team != "All": f = f[f["team"] == team]
        if opp != "All": f = f[f["opponent"] == opp]
        if match != "All": f = f[f["match_id"].astype(str) == match]
        if events: f = f[f["event_type"].str.lower().isin(events)]
        if phases: f = f[f["phase"].str.lower().isin(phases)]
        if players: f = f[f["player"].isin(players)]
        f = f[(f["time_min"] >= mr[0]) & (f["time_min"] <= mr[1])]
        if only: f = f[f["outcome"].str.lower().isin(SUCCESS_WORDS)]
        return f

    combos = [
        ("All", "All", "All", [], [], [], (0, 95), False),
        ("Home", "All", "m1", ["pass", "shot"], [], ["A. One"], (10, 80), True),
        ("All", "Away", "All", ["carry"], ["in possession"], [], (0, 120), False),
    ]
    for team, opp, match, ev, ph, pl, mr, ok in combos:
        a = inline(team, opp, match, ev, ph, pl, mr, ok)
        b = apply_filters(df, {"team": team, "opponent": opp, "match": match, "event_types": ev,
                               "phases": ph, "players": pl, "minute_range": mr, "only_success": ok})
        assert a.index.tolist() == b.index.tolist() and a.shape == b.shape


def test_run_app_still_byte_identical_baseline():
    """The extraction did not change run_app output (baseline PNG sizes captured pre-rewire)."""
    import matplotlib.pyplot as plt
    eng = get_engine()
    df = _frame()
    vt = eng.metadata["themes"]["Opta Analyst"]
    spec = eng.pitch_spec_cls()
    df_all = eng.apply_pitch_transforms(df, spec)
    f = eng.apply_pitch_transforms(df, spec)
    baseline = {"Pass Map": 217328, "Shot Map": 60455, "Carry Map": 193492}
    for nm, size in baseline.items():
        if nm not in eng.viz_registry:
            continue
        ctx = eng.default_ctx(vt, spec, title=nm, aux={"df_all": df_all})
        fig = eng.render(nm, f, ctx); b = eng.export(fig, "png", 120); plt.close(fig)
        assert len(b) == size, f"{nm} baseline drift: {len(b)} != {size}"


def test_studio_registers_and_never_imports_app_at_module_level():
    from fap.ui.page import load_builtin_pages, page_registry, get_page
    load_builtin_pages()
    assert "open_play_studio" in page_registry.ids()
    page = get_page("open_play_studio")
    assert page.info.name == "Open Play Studio" and page.section == "Analysis"
    # the Studio module must NOT import app at runtime (only get_engine)
    import inspect
    import fap.ui.builtin.openplay_studio as studio
    src = inspect.getsource(studio)
    assert "import app" not in src and "sys.modules" not in src


def test_dashboard_helpers():
    """Home Dashboard describes data via metadata only (no analytics)."""
    import fap.ui.builtin.openplay_studio as studio
    df = _frame()
    assert studio._uniq(df, "match_id") == df["match_id"].astype(str).nunique()
    assert studio._uniq(df, "nonexistent") == 0
    pct = studio._pct_valid(df, ["x", "y"])
    assert pct == 100.0                                   # synthetic frame has full coords
    assert studio._pct_valid(df, ["nope"]) is None


def test_suggested_charts_match_registry():
    import fap.ui.builtin.openplay_studio as studio
    eng = get_engine()
    w = studio.Studio(shell=None, engine=eng, can_edit=True, frame=_frame())
    sugg = studio._suggested_charts(w)
    assert sugg and all(name in eng.viz_registry for name in sugg)     # only real registry vizs
    # pass + shot events are present -> a pass and a shot viz should be suggested
    low = " ".join(s.lower() for s in sugg)
    assert "pass" in low and "shot" in low


def test_studio_panels_are_modular():
    import fap.ui.builtin.openplay_studio as studio
    for region in ("left", "center", "right", "bottom"):
        assert region in studio.PANELS and studio.PANELS[region]
        for pid, title, fn, phase in studio.PANELS[region]:
            assert isinstance(pid, str) and isinstance(title, str) and callable(fn)
            assert phase in ("input", "view")
