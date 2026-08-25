"""Checkpoint 8 — finalize inference API: benchmarks, metadata, examples,
cross-process determinism. Does NOT retrain or modify the frozen model.

Usage (from internal-xg/):
    python scripts/checkpoint8_report.py
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xg import api  # noqa: E402

lines: list[str] = []
def w(*a): lines.append(" ".join(str(x) for x in a))


def _rng_shots(n, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "team": rng.choice(["A", "B"], n),
        "shot_x": rng.uniform(80, 120, n), "shot_y": rng.uniform(10, 70, n),
        "body_part": rng.choice(["Right Foot", "Left Foot", "Head"], n),
        "shot_type": rng.choice(["Open Play", "Free Kick"], n, p=[0.92, 0.08]),
        "assist_type": rng.choice(["none", "pass", "cross", "through_ball"], n),
        "assisted": rng.choice([True, False], n),
        "set_piece": rng.choice([True, False], n, p=[0.2, 0.8]),
        "free_kick": False, "penalty": rng.choice([True, False], n, p=[0.02, 0.98]),
    })


def main() -> None:
    w("=" * 72); w("CHECKPOINT 8 — PRODUCTION INFERENCE API"); w("=" * 72)

    # ---- metadata ----
    info = api.model_info()
    w("\n[METADATA] api.model_info():")
    for k in ["model_name", "model_version", "model_type", "frozen", "training_data_source",
              "training_matches", "training_shots", "n_shots_nonpenalty", "calibration_method",
              "penalty_xg", "training_date"]:
        w(f"  {k}: {info.get(k)}")
    w(f"  features: {info['features']}")
    w(f"  hyperparameters: {info['hyperparameters']}")
    w(f"  package_versions: {info['software_versions']}")
    w(f"  final_metrics: {info['final_metrics_primary_test']}")

    # ---- input schema ----
    sch = api.input_schema()
    w("\n[INPUT SCHEMA] api.input_schema():")
    w(f"  required: {sch['required']}   penalty_column: {sch['penalty_column']}")
    w(f"  optional: {sch['optional']}")
    w(f"  coordinate_system: {sch['coordinate_system']}")

    # ---- example predictions ----
    w("\n[EXAMPLES] example predictions")
    examples = pd.DataFrame([
        {"label": "close central foot", "shot_x": 114, "shot_y": 40, "body_part": "Right Foot",
         "shot_type": "Open Play", "assist_type": "pass", "assisted": True, "set_piece": False,
         "free_kick": False, "penalty": False},
        {"label": "header from cross", "shot_x": 110, "shot_y": 46, "body_part": "Head",
         "shot_type": "Open Play", "assist_type": "cross", "assisted": True, "set_piece": False,
         "free_kick": False, "penalty": False},
        {"label": "25m free kick", "shot_x": 95, "shot_y": 40, "body_part": "Right Foot",
         "shot_type": "Free Kick", "assist_type": "none", "assisted": False, "set_piece": True,
         "free_kick": True, "penalty": False},
        {"label": "penalty", "shot_x": 108, "shot_y": 40, "body_part": "Right Foot",
         "shot_type": "Penalty", "assist_type": "none", "assisted": False, "set_piece": True,
         "free_kick": False, "penalty": True},
    ])
    scored = api.predict_xg(examples)
    for _, r in scored.iterrows():
        w(f"  {r['label']:22s} xG={r['xg']:.4f}")
    w(f"  team xG (all)  = {api.calculate_team_xg(examples):.4f}")
    w(f"  npxG (no pens) = {api.calculate_npxg(examples):.4f}")

    # ---- performance benchmark ----
    w("\n[PERFORMANCE] vectorized inference (best of 3 after warmup)")
    api.predict_xg(_rng_shots(10))  # warmup
    for n in [1, 20, 100, 1000, 10000]:
        d = _rng_shots(n, seed=n)
        best = min(_time(lambda: api.predict_xg(d)) for _ in range(3))
        per = best / n * 1e6
        w(f"  {n:6d} shots: {best*1e3:8.2f} ms total   {per:7.2f} us/shot")

    # ---- cross-process determinism ----
    w("\n[DETERMINISM] same input -> same xG (repeat, and separate process)")
    d = _rng_shots(200, seed=7)
    h1 = _hash(api.predict_xg(d)["xg"].to_numpy())
    h2 = _hash(api.predict_xg(d)["xg"].to_numpy())
    w(f"  in-process repeat: {h1 == h2}  (hash {h1[:12]})")
    # separate process
    snippet = (
        "import sys;sys.path.insert(0,r'%s');"
        "import numpy as np,pandas as pd,hashlib;from xg import api;"
        "rng=np.random.default_rng(7);"
        "d=pd.DataFrame({'team':rng.choice(['A','B'],200),'shot_x':rng.uniform(80,120,200),"
        "'shot_y':rng.uniform(10,70,200),'body_part':rng.choice(['Right Foot','Left Foot','Head'],200),"
        "'shot_type':rng.choice(['Open Play','Free Kick'],200,p=[0.92,0.08]),"
        "'assist_type':rng.choice(['none','pass','cross','through_ball'],200),"
        "'assisted':rng.choice([True,False],200),'set_piece':rng.choice([True,False],200,p=[0.2,0.8]),"
        "'free_kick':False,'penalty':rng.choice([True,False],200,p=[0.02,0.98])});"
        "open(r'%s','w').write(hashlib.sha256(np.ascontiguousarray(api.predict_xg(d)['xg'].to_numpy()).tobytes()).hexdigest())"
    ) % (str(ROOT / "src"), str(ROOT / "reports" / "_proc_hash.txt"))
    pyw = Path(sys.executable)
    subprocess.run([str(pyw), "-c", snippet], check=False)
    time.sleep(1)
    proc_hash = (ROOT / "reports" / "_proc_hash.txt").read_text().strip()
    w(f"  separate process matches in-process: {proc_hash == h1}  (hash {proc_hash[:12]})")

    (ROOT / "reports" / "checkpoint8_report.txt").write_text("\n".join(lines), encoding="utf-8")


def _time(fn):
    t = time.perf_counter(); fn(); return time.perf_counter() - t


def _hash(arr):
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


if __name__ == "__main__":
    main()
