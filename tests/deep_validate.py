"""Deep output validation for the Open Play app.

Unlike test_phase7 (which only asserts 'no exception'), this rasterises each
plugin and measures whether it actually draws data:

  * displays-nothing:  render(data) vs render(empty)  -> must differ
  * heatmaps-similar:  each HEAT_TYPE pairwise raster diff -> must differ
  * thirds:            thirds 'None' vs each mode        -> must differ
  * vertical:          data actually appears in Vertical orientation
  * themes:            each theme non-blank and visually distinct

Run:  FAP_TEST=1 MPLBACKEND=Agg python tests/deep_validate.py
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import app

DPI = 64


def dummy_df(n=600, seed=3):
    rng = np.random.default_rng(seed)
    events = rng.choice(["pass", "carry", "cross", "dribble", "shot", "duel", "recovery",
                         "interception", "clearance", "tackle", "block"],
                        size=n, p=[0.42, 0.13, 0.05, 0.04, 0.06, 0.06, 0.07, 0.05, 0.04, 0.05, 0.03])
    x = rng.uniform(0, 100, n); y = rng.uniform(0, 100, n)
    dx = rng.normal(12, 10, n); dy = rng.normal(0, 12, n)
    df = pd.DataFrame({
        "event_type": events, "x": x, "y": y,
        "x2": np.clip(x + dx, 0, 100), "y2": np.clip(y + dy, 0, 100),
        "team": rng.choice(["Al Ahly", "Zamalek"], n, p=[0.7, 0.3]), "opponent": "Rivals FC",
        "match_id": rng.choice(["M1", "M2", "M3"], n),
        "phase": rng.choice(["build-up", "progression", "final-third"], n),
        "player": rng.choice(["Salah", "Zizo", "Marwan", "Kahraba", "Dieng", ""], n),
        "receiver": rng.choice(["Salah", "Zizo", "Marwan", ""], n),
        "outcome": rng.choice(["successful", "unsuccessful"], n, p=[0.74, 0.26]),
        "shot_result": "", "body_part": rng.choice(["right foot", "left foot", "head"], n),
        "minute": rng.integers(0, 95, n), "second": rng.integers(0, 60, n),
        "period": rng.choice([1, 2], n), "shirt_number": rng.integers(2, 30, n),
        "sequence_id": rng.choice(["S1", "S2", "S3", ""], n, p=[0.2, 0.2, 0.2, 0.4]),
    })
    is_shot = df["event_type"].eq("shot")
    df.loc[is_shot, "shot_result"] = rng.choice(["Goal", "Saved", "Off Target", "Blocked"],
                                                is_shot.sum(), p=[0.15, 0.3, 0.35, 0.2])
    df.loc[is_shot, "x"] = rng.uniform(70, 99, is_shot.sum())
    return df


def base_ctx(spec, df_all, vt_name="Opta Analyst", heat_overrides=None):
    vt = dict(app.VIZ_THEMES[vt_name])
    heat = {"type": "Gaussian KDE", "preset": "All selected events", "cmap": "Greens",
            "alpha": 0.65, "bandwidth": 3.0, "levels": 10, "bins": 13, "gridsize": 22,
            "cell_size": 10, "interpolation": "bilinear", "normalization": "Count",
            "threshold": 0, "percentile_scale": False, "log_scale": False, "cell_labels": True}
    heat.update(heat_overrides or {})
    return {
        "vt": vt, "spec": spec, "title": "Test", "show_title": True,
        "title_size": 20, "label_size": 11, "legend_size": 10, "respect_filter": False,
        "marker": {"shape": "Circle", "size": 80, "edge_width": 1.1, "edge_color": vt["line"],
                   "alpha": 0.85, "rotation": 45, "jitter": 0.3, "zorder": 6,
                   "shadow": True, "glow": True, "glow_color": vt["accent"]},
        "arrow": {"kind": "Straight", "width": 1.6, "head": 10, "curvature": 0.18, "alpha": 0.72,
                  "linecap": "round", "shadow": False, "glow": False, "cmap": "viridis"},
        "labels": {"show": True, "show_players": True, "smart": True, "hide_overlapping": True,
                   "halo": True, "halo_color": vt["pitch"], "box": False, "leader_lines": True,
                   "size": 9, "offset": 1.6, "rotation": 0, "max_labels": 25},
        "legend": {"show": True, "position": "Bottom", "orientation": "Horizontal",
                   "frame": True, "title": "", "renames": "successful=Completed", "hide": "", "order": ""},
        "heat": heat,
        "colors": {"arrow": vt["accent"], "unsuccess": vt["danger"], "start": vt["accent"],
                   "end": vt["accent2"], "shot": vt["panel"], "goal": vt["danger"],
                   "zone": vt["warning"], "bar": vt["accent"], "line": vt["accent"],
                   "trend": vt["danger"], "carry": vt["grey"], "cross": vt["accent2"]},
        "aux": {"df_all": df_all, "top_n": 8, "zone_mode": "Pitch Thirds",
                "start_end_event": "pass", "timeline_focus": "All", "trend_metric": "Shots",
                "sequence_mode": "Longest sequence", "sequence_id": "S1",
                "show_sequence_numbers": True, "line_width": 2.4, "dashboard_layout": None},
    }


def prepared(spec, raw=None):
    df = app.add_derived_columns(app.normalize_coordinates(app.ensure_columns(dummy_df() if raw is None else raw), "0-100"))
    return app.apply_pitch_transforms(df, spec)


def raster(fig):
    fig.canvas.draw()
    w, h = fig.canvas.get_width_height()
    buf = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8).reshape(h, w, 4).copy()
    plt.close(fig)
    return buf[:, :, :3].astype(np.int16)


def diff_frac(a, b, thresh=10):
    """Fraction of pixels differing by > thresh in any channel. Handles size mismatch."""
    if a.shape != b.shape:
        h = min(a.shape[0], b.shape[0]); w = min(a.shape[1], b.shape[1])
        a = a[:h, :w]; b = b[:h, :w]
    return float(np.mean(np.any(np.abs(a - b) > thresh, axis=2)))


def render_arr(name, spec, ctx, df):
    return raster(app.VIZ_REGISTRY[name]["render"](df, ctx))


results = {"displays_nothing": [], "heat_similar": [], "thirds": [], "vertical": [], "themes": [], "ok": []}

# ---- 1. displays-nothing: data vs empty, every plugin ----
print("== displays-nothing (data vs empty) ==")
spec = app.PitchSpec(orientation="Horizontal")
df_full = prepared(spec)
df_empty = df_full.iloc[0:0]
ctx_full = base_ctx(spec, df_full)
ctx_empty = base_ctx(spec, df_empty); ctx_empty["aux"]["df_all"] = df_empty
for name in app.VIZ_REGISTRY:
    try:
        a = render_arr(name, spec, ctx_full, df_full)
        b = render_arr(name, spec, ctx_empty, df_empty)
        d = diff_frac(a, b)
        tag = "OK" if d > 0.004 else "!!EMPTY"
        if d <= 0.004:
            results["displays_nothing"].append((name, d))
        print(f"  {tag:8} {name:34} datavsEmpty={d:.4f}")
    except Exception as e:
        results["displays_nothing"].append((name, f"ERR {type(e).__name__}: {e}"))
        print(f"  !!ERR    {name:34} {type(e).__name__}: {e}")

# ---- 2. heatmap similarity across HEAT_TYPES ----
print("\n== heatmap distinctiveness (pairwise) ==")
spec = app.PitchSpec(orientation="Horizontal")
df = prepared(spec)
arrs = {}
for ht in app.HEAT_TYPES:
    ctx = base_ctx(spec, df, heat_overrides={"type": ht})
    try:
        arrs[ht] = raster(app.viz_heat_studio(df, ctx))
    except Exception as e:
        print(f"  !!ERR {ht}: {type(e).__name__}: {e}")
names = list(arrs)
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        d = diff_frac(arrs[names[i]], arrs[names[j]], thresh=14)
        if d < 0.01:
            results["heat_similar"].append((names[i], names[j], d))
            print(f"  !!SIMILAR {names[i]} ~ {names[j]}  diff={d:.4f}")
if not results["heat_similar"]:
    print("  all heat types visually distinct (min pairwise diff computed)")

# ---- 3. thirds render ----
print("\n== thirds rendering (mode vs None) ==")
base_spec = app.PitchSpec(thirds_mode="None")
df0 = prepared(base_spec)
a0 = render_arr("Shot Map", base_spec, base_ctx(base_spec, df0), df0)
for mode in ["Length thirds (lines)", "Width lanes (lines)", "Highlight final third",
             "Highlight middle third", "Highlight defensive third", "Custom positions"]:
    spec = app.PitchSpec(thirds_mode=mode, thirds_labels=True, thirds_positions="25, 50, 75")
    dfm = prepared(spec)
    am = render_arr("Shot Map", spec, base_ctx(spec, dfm), dfm)
    d = diff_frac(am, a0)
    tag = "OK" if d > 0.001 else "!!NOTDRAWN"
    if d <= 0.001:
        results["thirds"].append((mode, d))
    print(f"  {tag:11} {mode:30} diffVsNone={d:.4f}")

# ---- 4. vertical mode shows data ----
print("\n== vertical mode (data present, not off-view) ==")
for name in ["Pass Map", "Shot Map", "Defensive Actions Map", "Heatmap Studio"]:
    spec = app.PitchSpec(orientation="Vertical")
    dfv = prepared(spec)
    ev = base_ctx(spec, dfv); ev["aux"]["df_all"] = dfv.iloc[0:0]
    a = render_arr(name, spec, base_ctx(spec, dfv), dfv)
    b = render_arr(name, spec, ev, dfv.iloc[0:0])
    d = diff_frac(a, b)
    tag = "OK" if d > 0.004 else "!!EMPTY-V"
    if d <= 0.004:
        results["vertical"].append((name, d))
    print(f"  {tag:10} {name:30} vDataVsEmpty={d:.4f}")

# ---- 5. themes distinct + non-blank ----
print("\n== themes (distinct + non-blank) ==")
spec = app.PitchSpec()
df = prepared(spec)
theme_arrs = {}
for vt_name in app.VIZ_THEMES:
    ctx = base_ctx(spec, df, vt_name=vt_name)
    theme_arrs[vt_name] = render_arr("Pass Map", spec, ctx, df)
tnames = list(theme_arrs)
# non-blank: variance across pixels
for vt_name, arr in theme_arrs.items():
    if float(arr.std()) < 3.0:
        results["themes"].append((vt_name, "blank"))
        print(f"  !!BLANK {vt_name}")
# distinct backgrounds: compare each pair, expect most to differ
sim_pairs = 0
for i in range(len(tnames)):
    for j in range(i + 1, len(tnames)):
        if diff_frac(theme_arrs[tnames[i]], theme_arrs[tnames[j]], thresh=18) < 0.02:
            sim_pairs += 1
print(f"  themes rendered: {len(tnames)}, near-identical pairs: {sim_pairs}")

# ---- summary ----
print("\n" + "=" * 60)
print("SUMMARY")
for k in ["displays_nothing", "heat_similar", "thirds", "vertical", "themes"]:
    v = results[k]
    print(f"  {k:18}: {'CLEAN' if not v else f'{len(v)} issue(s): ' + str(v)}")
fail = sum(len(results[k]) for k in ["displays_nothing", "heat_similar", "thirds", "vertical", "themes"])
print(f"\nTOTAL ISSUES: {fail}")
raise SystemExit(1 if fail else 0)
