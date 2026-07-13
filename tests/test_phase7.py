"""Phase 7 smoke tests: render every registered plugin headless with no exceptions."""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import app  # noqa: E402


def dummy_df(n=600, seed=3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    events = rng.choice(["pass", "carry", "cross", "dribble", "shot", "duel", "recovery",
                         "interception", "clearance", "tackle", "block"],
                        size=n, p=[0.42, 0.13, 0.05, 0.04, 0.06, 0.06, 0.07, 0.05, 0.04, 0.05, 0.03])
    x = rng.uniform(0, 100, n)
    y = rng.uniform(0, 100, n)
    dx = rng.normal(12, 10, n)
    dy = rng.normal(0, 12, n)
    df = pd.DataFrame({
        "event_type": events,
        "x": x, "y": y,
        "x2": np.clip(x + dx, 0, 100), "y2": np.clip(y + dy, 0, 100),
        "team": rng.choice(["Al Ahly", "Zamalek"], n, p=[0.7, 0.3]),
        "opponent": "Rivals FC",
        "match_id": rng.choice(["M1", "M2", "M3"], n),
        "phase": rng.choice(["build-up", "progression", "final-third"], n),
        "player": rng.choice(["Salah", "Zizo", "Marwan", "Kahraba", "Dieng", ""], n),
        "receiver": rng.choice(["Salah", "Zizo", "Marwan", ""], n),
        "outcome": rng.choice(["successful", "unsuccessful"], n, p=[0.74, 0.26]),
        "shot_result": "",
        "body_part": rng.choice(["right foot", "left foot", "head"], n),
        "minute": rng.integers(0, 95, n),
        "second": rng.integers(0, 60, n),
        "period": rng.choice([1, 2], n),
        "shirt_number": rng.integers(2, 30, n),
        "sequence_id": rng.choice(["S1", "S2", "S3", ""], n, p=[0.2, 0.2, 0.2, 0.4]),
    })
    is_shot = df["event_type"].eq("shot")
    df.loc[is_shot, "shot_result"] = rng.choice(["Goal", "Saved", "Off Target", "Blocked"],
                                                is_shot.sum(), p=[0.15, 0.3, 0.35, 0.2])
    df.loc[is_shot, "x"] = rng.uniform(70, 99, is_shot.sum())
    return df


def base_ctx(spec: "app.PitchSpec", df_all: pd.DataFrame, vt_name="Opta Analyst",
             heat_overrides=None, arrow_overrides=None) -> dict:
    vt = dict(app.VIZ_THEMES[vt_name])
    heat = {"type": "Gaussian KDE", "preset": "All selected events", "cmap": "Greens",
            "alpha": 0.65, "bandwidth": 3.0, "levels": 10, "bins": 13, "gridsize": 22,
            "cell_size": 10, "interpolation": "bilinear", "normalization": "Count",
            "threshold": 0, "percentile_scale": False, "log_scale": False, "cell_labels": True}
    heat.update(heat_overrides or {})
    arrow = {"kind": "Straight", "width": 1.6, "head": 10, "curvature": 0.18, "alpha": 0.72,
             "linecap": "round", "shadow": False, "glow": False, "cmap": "viridis"}
    arrow.update(arrow_overrides or {})
    return {
        "vt": vt, "spec": spec, "title": "Test", "show_title": True,
        "title_size": 20, "label_size": 11, "legend_size": 10, "respect_filter": False,
        "marker": {"shape": "Circle", "size": 80, "edge_width": 1.1, "edge_color": vt["line"],
                   "alpha": 0.85, "rotation": 45, "jitter": 0.3, "zorder": 6,
                   "shadow": True, "glow": True, "glow_color": vt["accent"]},
        "arrow": arrow,
        "labels": {"show": True, "show_players": True, "smart": True, "hide_overlapping": True,
                   "halo": True, "halo_color": vt["pitch"], "box": False, "leader_lines": True,
                   "size": 9, "offset": 1.6, "rotation": 0, "max_labels": 25},
        "legend": {"show": True, "position": "Bottom", "orientation": "Horizontal",
                   "frame": True, "title": "", "renames": "successful=Completed",
                   "hide": "", "order": ""},
        "heat": heat,
        "colors": {"arrow": vt["accent"], "unsuccess": vt["danger"], "start": vt["accent"],
                   "end": vt["accent2"], "shot": vt["panel"], "goal": vt["danger"],
                   "zone": vt["warning"], "bar": vt["accent"], "line": vt["accent"],
                   "trend": vt["danger"], "carry": vt["grey"], "cross": vt["accent2"]},
        "aux": {"df_all": df_all, "top_n": 8, "zone_mode": "Pitch Thirds",
                "start_end_event": "pass", "timeline_focus": "All",
                "trend_metric": "Shots", "sequence_mode": "Longest sequence",
                "sequence_id": "S1", "show_sequence_numbers": True,
                "line_width": 2.4, "dashboard_layout": None},
    }


def prepared(spec):
    df = app.add_derived_columns(app.normalize_coordinates(app.ensure_columns(dummy_df()), "0-100"))
    return app.apply_pitch_transforms(df, spec)


def run_all():
    passed = failed = 0
    failures = []

    def check(label, fn):
        nonlocal passed, failed
        try:
            fig = fn()
            assert fig is not None
            plt.close(fig)
            passed += 1
        except Exception as e:
            failed += 1
            failures.append(f"{label}: {type(e).__name__}: {e}")

    # 1) Every registered plugin, both orientations
    for orient in ["Horizontal", "Vertical"]:
        spec = app.PitchSpec(orientation=orient)
        df = prepared(spec)
        ctx = base_ctx(spec, df)
        for name, entry in app.VIZ_REGISTRY.items():
            check(f"{name} [{orient}]", lambda e=entry, d=df, c=ctx: e["render"](d, c))

    # 2) All pitch views + auto orientation + mirror/flip
    for view in app.PITCH_VIEWS:
        spec = app.PitchSpec(orientation="Auto", view=view, mirror=True, flip_y=True,
                             custom_crop=(20, 90, 10, 90))
        df = prepared(spec)
        ctx = base_ctx(spec, df)
        check(f"Pass Map view={view}", lambda d=df, c=ctx: app.VIZ_REGISTRY["Pass Map"]["render"](d, c))

    # 3) All thirds modes
    for mode in ["None", "Length thirds (lines)", "Width lanes (lines)", "Length thirds + lanes",
                 "Highlight final third", "Highlight middle third", "Highlight defensive third",
                 "Highlight attacking half", "Highlight defensive half", "Custom positions"]:
        spec = app.PitchSpec(thirds_mode=mode, thirds_labels=True, lane_lines=True)
        df = prepared(spec)
        ctx = base_ctx(spec, df)
        check(f"Thirds={mode}", lambda d=df, c=ctx: app.VIZ_REGISTRY["Shot Map"]["render"](d, c))

    # 4) All heat types x both orientations + scaling options
    for orient in ["Horizontal", "Vertical"]:
        spec = app.PitchSpec(orientation=orient)
        df = prepared(spec)
        for ht in app.HEAT_TYPES:
            ctx = base_ctx(spec, df, heat_overrides={"type": ht, "threshold": 20,
                                                     "percentile_scale": True, "log_scale": True,
                                                     "normalization": "Percent"})
            check(f"Heat {ht} [{orient}]", lambda d=df, c=ctx: app.viz_heat_studio(d, c))
        for preset in app.HEAT_PRESETS:
            ctx = base_ctx(spec, df, heat_overrides={"preset": preset})
            check(f"Heat preset {preset} [{orient}]", lambda d=df, c=ctx: app.viz_heat_studio(d, c))

    # 5) All arrow kinds
    for kind in ["Straight", "Curved", "Bezier", "Dashed", "Dotted", "Double Arrow",
                 "Comet", "Gradient Comet"]:
        spec = app.PitchSpec()
        df = prepared(spec)
        ctx = base_ctx(spec, df, arrow_overrides={"kind": kind, "glow": True, "shadow": True})
        check(f"Arrow {kind}", lambda d=df, c=ctx: app.VIZ_REGISTRY["Pass Map"]["render"](d, c))

    # 6) All marker shapes
    for shape in app.MARKER_SHAPES:
        spec = app.PitchSpec()
        df = prepared(spec)
        ctx = base_ctx(spec, df)
        ctx["marker"]["shape"] = shape
        check(f"Marker {shape}", lambda d=df, c=ctx: app.VIZ_REGISTRY["Defensive Actions Map"]["render"](d, c))

    # 7) Every viz theme
    for vt_name in app.VIZ_THEMES:
        spec = app.PitchSpec()
        df = prepared(spec)
        ctx = base_ctx(spec, df, vt_name=vt_name)
        check(f"Theme {vt_name}", lambda d=df, c=ctx: app.VIZ_REGISTRY["Match Summary Dashboard"]["render"](d, c))

    # 8) Sequence modes
    for mode in ["Specific sequence", "Latest shot sequence", "Latest goal sequence", "Longest sequence"]:
        spec = app.PitchSpec()
        df = prepared(spec)
        ctx = base_ctx(spec, df)
        ctx["aux"]["sequence_mode"] = mode
        check(f"Sequence {mode}", lambda d=df, c=ctx: app.viz_sequence(d, c))

    # 9) Export formats produce bytes identical facecolor path
    spec = app.PitchSpec()
    df = prepared(spec)
    ctx = base_ctx(spec, df)
    fig = app.VIZ_REGISTRY["Pass Map"]["render"](df, ctx)
    for fmt in ["png", "svg", "pdf"]:
        data = app.fig_to_bytes(fig, fmt=fmt, dpi=150)
        assert len(data) > 1000, f"export {fmt} too small"
        passed += 1
    plt.close(fig)

    # 10) Empty dataframe safety
    empty = prepared(app.PitchSpec()).iloc[0:0]
    ctx = base_ctx(app.PitchSpec(), empty)
    ctx["aux"]["df_all"] = empty
    for name in ["Heatmap Studio", "Pass Map", "Shot Map", "Sequence Map", "Statistical Table",
                 "Match Summary Cards", "Event Distribution Bar", "Timeline Line Chart"]:
        check(f"EMPTY {name}", lambda e=app.VIZ_REGISTRY[name], c=ctx: e["render"](empty, c))

    print(f"\nPASSED: {passed}  FAILED: {failed}")
    for f_ in failures:
        print("  FAIL:", f_)
    return failed


if __name__ == "__main__":
    raise SystemExit(1 if run_all() else 0)
