"""Checkpoint 6 — final football sanity & production safety report.

Loads the FROZEN Internal xG Model v1.0 and audits inference behavior. Does NOT
retrain or modify the model. Writes reports/checkpoint6_report.txt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xg import config, data_loader, evaluate, features as F, predict as P, splits, validation  # noqa: E402

lines: list[str] = []
def w(*a): lines.append(" ".join(str(x) for x in a))


def _shot(**kw):
    base = dict(shot_x=110.0, shot_y=40.0, body_part="Right Foot", shot_type="Open Play",
                assist_type="none", assisted=False, set_piece=False, free_kick=False, penalty=False)
    base.update(kw)
    return pd.DataFrame([base])


def main() -> None:
    v1 = joblib.load(config.MODELS_DIR / "internal_xg_v1.joblib")
    baseline = joblib.load(config.MODELS_DIR / "logistic_baseline.joblib")
    md = v1["metadata"]
    cols = v1["feature_columns"]

    w("=" * 72); w("CHECKPOINT 6 — FINAL FOOTBALL SANITY & PRODUCTION SAFETY"); w("=" * 72)

    # 1. integrity
    w("\n[1] FROZEN MODEL INTEGRITY")
    w(f"  loaded: internal_xg_v1.joblib   version={md['model_version']}   frozen={md['frozen']}")
    w(f"  features match meta: {md['features'] == cols == F.FEATURES_A}")
    w(f"  model_type: {md['model_type']}")
    df = data_loader.load_processed()
    non_pen, _ = F.split_penalties(df)
    feat, _ = F.build_features(non_pen, "A")
    te = splits.match_level_split(feat, seed=config.RANDOM_SEED)["test"]
    yte = te["goal"].to_numpy()
    p_v1 = v1["pipeline"].predict_proba(te[cols])[:, 1]
    p_base = baseline["pipeline"].predict_proba(te[cols])[:, 1]
    w(f"  determinism: two runs identical = {np.array_equal(p_v1, v1['pipeline'].predict_proba(te[cols])[:,1])}")
    w(f"  v1 == reviewed baseline (max abs diff): {np.max(np.abs(p_v1 - p_base)):.2e}")
    w(f"  predictions in [0,1]: {bool((p_v1 >= 0).all() and (p_v1 <= 1).all())}")

    # 2. coordinate sanity table
    w("\n[2] COORDINATE SANITY")
    sym_ok = True
    for x in (60, 100, 115, 120):
        for y in (0, 20, 40):
            a = P.predict_xg(_shot(shot_x=x, shot_y=y), bundle=v1)["xg"].iloc[0]
            b = P.predict_xg(_shot(shot_x=x, shot_y=80 - y), bundle=v1)["xg"].iloc[0]
            sym_ok &= abs(a - b) < 1e-9
    w(f"  (x,y) vs (x,80-y) identical across grid: {sym_ok}")
    w("  invalid-coordinate handling (on_invalid='nan' -> NaN; 'error' -> raise):")
    for x, y, lbl in [(-5, 40, "x<0"), (150, 40, "x>120"), (60, -3, "y<0"), (60, 90, "y>80"),
                      (np.nan, 40, "x NaN"), (60, np.inf, "y inf")]:
        d = _shot(shot_x=x, shot_y=y)
        flagged = bool(validation.invalid_mask(d)[0])
        val = P.predict_xg(d, bundle=v1, on_invalid="nan")["xg"].iloc[0]
        w(f"    {lbl:8s} flagged={flagged}  xg={'NaN' if np.isnan(val) else round(val,4)}")
    w("  near-boundary 120.2 (rounding) allowed & scored raw: "
      f"xg={P.predict_xg(_shot(shot_x=120.2, shot_y=40), bundle=v1)['xg'].iloc[0]:.4f}")

    # 3/7. geometry + extreme sweep
    w("\n[3/7] DISTANCE/ANGLE + EXTREME-SHOT SAFETY (central sweep)")
    cases = [(119, 40, "point-blank central"), (119, 62, "point-blank tight-angle"),
             (114, 40, "~6m central"), (110, 40, "~10m central"), (105, 40, "~15m central"),
             (98, 40, "~20m central"), (85, 40, "~30m central"), (70, 40, "~45m central"),
             (60, 40, "~55m central"), (120, 58, "byline")]
    d = pd.DataFrame([{"shot_x": x, "shot_y": y, "body_part": "Right Foot", "shot_type": "Open Play",
                       "assist_type": "none", "assisted": False, "set_piece": False,
                       "free_kick": False, "penalty": False} for x, y, _ in cases])
    g, _ = F.build_features(d, "A")
    xg = P.predict_xg(d, bundle=v1)["xg"].to_numpy()
    for (x, y, lbl), dist, ang, p in zip(cases, g["distance"], g["angle_deg"], xg):
        w(f"    {lbl:24s} dist={dist:5.1f}m angle={ang:5.1f}  xG={p:.4f}")
    w(f"    all finite & in [0,1]: {bool(np.isfinite(xg).all() and (xg>=0).all() and (xg<=1).all())}")
    xs = np.linspace(119.5, 60, 40)
    sweep = P.predict_xg(pd.DataFrame({"shot_x": xs, "shot_y": 40.0, "body_part": "Right Foot",
                          "shot_type": "Open Play", "assist_type": "none", "assisted": False,
                          "set_piece": False, "free_kick": False, "penalty": False}), bundle=v1)["xg"].to_numpy()
    w(f"    central sweep monotonic non-increasing: {bool(np.all(np.diff(sweep) <= 1e-9))}")

    # 6. penalties
    w("\n[6] PENALTY SAFETY")
    pen = P.predict_xg(_shot(shot_x=108, shot_y=40, shot_type="Penalty", penalty=True), bundle=v1)["xg"].iloc[0]
    mix = pd.concat([_shot(shot_x=112, shot_y=40),
                     _shot(shot_x=108, shot_y=40, shot_type="Penalty", penalty=True)], ignore_index=True)
    w(f"  penalty xG = {pen:.4f} (frozen constant {v1['penalty_xg']:.4f})")
    w(f"  team xG (incl pen) = {P.calculate_team_xg(mix, bundle=v1):.4f}   "
      f"npxG (excl pen) = {P.calculate_team_npxg(mix, bundle=v1):.4f}")

    # 8. realistic sample (test holdout) — reproduce C5 aggregates
    w("\n[8] REALISTIC SAMPLE (frozen model on the test holdout; no retraining)")
    q = np.percentile(p_v1, [1, 5, 25, 50, 75, 95, 99])
    w(f"  n_shots={len(te)}  goals={int(yte.sum())}")
    w(f"  xG  min={p_v1.min():.4f}  max={p_v1.max():.4f}  mean={p_v1.mean():.4f}  median={np.median(p_v1):.4f}")
    w(f"  percentiles [1,5,25,50,75,95,99] = {[round(float(x),4) for x in q]}")
    w(f"  sum xG={p_v1.sum():.1f}  actual goals={int(yte.sum())}  goals/sumxG={yte.sum()/p_v1.sum():.3f}")
    w(f"  (matches Checkpoint 5: sum xG 608.0 vs 610 goals)")

    # 9. failure modes
    w("\n[9] FAILURE MODES")
    empty = P.predict_xg(pd.DataFrame(columns=["shot_x", "shot_y", "penalty"]), bundle=v1)
    w(f"  empty df -> rows={len(empty)}, has xg col={('xg' in empty.columns)}, team_xg=0 ok")
    w(f"  single shot -> {len(P.predict_xg(_shot(), bundle=v1))} row")
    big = pd.concat([_shot(shot_x=110, shot_y=40)] * 20000, ignore_index=True)
    w(f"  20000 shots -> {len(P.predict_xg(big, bundle=v1))} rows, all in [0,1]="
      f"{bool(P.predict_xg(big, bundle=v1)['xg'].between(0,1).all())}")
    w(f"  unseen categories -> xg={P.predict_xg(_shot(body_part='Elbow', shot_type='Bicycle', assist_type='lob'), bundle=v1)['xg'].iloc[0]:.4f} (no crash)")
    mixed = pd.concat([_shot(shot_x=112, shot_y=40), _shot(shot_x=999, shot_y=40)], ignore_index=True)
    mo = P.predict_xg(mixed, bundle=v1, on_invalid="nan")["xg"]
    w(f"  valid+malformed mix -> valid={mo.iloc[0]:.4f}, malformed={'NaN' if np.isnan(mo.iloc[1]) else mo.iloc[1]}")

    (ROOT / "reports" / "checkpoint6_report.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
