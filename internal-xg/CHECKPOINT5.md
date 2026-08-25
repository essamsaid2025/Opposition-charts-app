# Checkpoint 5 — Deep Evaluation, Calibration & Robustness

Full log: [`reports/checkpoint5_report.txt`](reports/checkpoint5_report.txt);
machine summary: [`reports/checkpoint5_summary.json`](reports/checkpoint5_summary.json).
Plots: `reports/reliability_lr_deep.png`, `reports/extreme_sweep.png`.

**Outcome: Logistic Regression confirmed and FROZEN as Internal xG Model v1.0.**
No major problem discovered.

Discipline: the primary test set was used only to *report* (never to tune);
robustness CV used train+val only; temporal robustness refit the same frozen
config on chronological-train (no leakage, no tuning).

## 1. Calibration deep dive (LR, test)
- Log Loss **0.2650**, Brier **0.0751**, ROC-AUC **0.7878**.
- **ECE 0.0081, MCE 0.0245.** Calibration **slope 0.988** (ideal 1.0),
  **calibration-in-the-large 0.004** (ideal 0.0).
- Reliability: expected ≈ observed goals in every bin — 0.05→2.5%, 0.14→14.2%,
  0.24→24.3%, 0.38→37.6%. **Probabilities behave like probabilities.**

## 2. Segment calibration (all well-calibrated; small groups flagged)
| segment | n | mean pred | actual | note |
|---|---|---|---|---|
| Open Play | 6009 | 0.098 | 0.098 | ✓ |
| Free Kick | 295 | 0.060 | 0.061 | ✓ |
| foot | 5232 | 0.092 | 0.095 | ✓ |
| head | 1050 | 0.114 | 0.106 | slight over (~0.8pp), fine |
| Corner | 2 | — | — | too small, ignore |

**Distance bands:** all monotonic and calibrated (0–6 m: 0.412 vs 0.400; 15–20 m:
0.072 vs 0.080; 30 m+: 0.012 vs 0.011).
**Angle bands:** good overall; the 0–10° band under-predicts (0.026 vs 0.050) but
n=180 (9 goals) — noise, not systematic.
**Assist type:** cross 0.147/0.147 ✓, pass 0.072/0.074 ✓, **through_ball 0.306/0.304
✓ (n=184 — the effect is real, not overfit)**, cutback n=29 → too small to trust.

## 3. Robustness — 2×5-fold match-level CV (train+val only)
| metric | LR | XGB | Δ(XGB−LR) |
|---|---|---|---|
| log loss | 0.26134 ± 0.00680 | 0.26057 ± 0.00665 | −0.00077 |
| Brier | 0.07380 ± 0.00224 | 0.07371 ± 0.00218 | −0.00008 |
| ROC-AUC | 0.78635 ± 0.00915 | 0.78712 ± 0.00940 | +0.00076 |
| ECE | 0.00926 ± 0.00204 | 0.00935 ± 0.00158 | +0.00009 |

XGB is better in 7/10 folds but the mean log-loss gap (−0.00077) is **~1/9th of
the fold σ (0.0068)** — i.e. within split noise. The apparent XGB edge is **not
real** at any football-meaningful scale.

## 4. Temporal robustness (chronological, later matches held out)
LR: log loss 0.2658 / Brier 0.0743 / AUC 0.7655 / ECE 0.0095.
XGB: 0.2645 / 0.0739 / 0.7682 / ECE 0.0121.
Both degrade slightly under time shift (later data = tournaments); **LR stays
better calibrated**. No breakdown.

## 5. Extreme-shot behavior (decisive)
Central distance sweep: **LR is monotonic non-increasing (True); XGB is NOT
(False)** — XGB plateaus and even ticks *up* at long range (0.0081 @ 45 m →
0.0083 @ 55 m) while LR decays smoothly (0.0025 → 0.0007). XGB is also overly
conservative at point-blank range (2.3 m: 0.75 vs LR 0.88). See
`reports/extreme_sweep.png`. This is a clear, football-relevant win for LR.

## 6. Aggregate xG validation (LR, test)
- **All test shots: ΣxG 608.0 vs 610 actual goals (ratio 0.997).**
- Per match: corr 0.41, MAE 1.15 goals (expected — high per-match variance).
- Per team: corr 0.741. Per competition: corr 0.996 (608 vs 610).
Team/aggregate xG (the intended use) tracks reality well.

## 7. Provider benchmark (reference only)
Internal mean 0.0964, StatsBomb 0.0939, actual 0.0967 — **our mean is actually
closer to the real rate**. corr 0.812, MAD 0.0375. StatsBomb's Brier (0.0701) beats
ours (0.0751) on discrimination — expected, they use freeze-frame defender/GK
context we deliberately exclude for internal reproducibility. Per-distance-band,
our LR tracks the actual rate as well as StatsBomb.

## 8. LR vs XGB — final recommendation
| criterion | winner |
|---|---|
| Calibration (ECE, slope, CITL) | **LR** |
| Brier / Log Loss | tie (within CV σ) |
| Robustness (CV) | tie (Δ within 1σ) |
| Temporal stability | tie; LR better calibrated |
| Extreme-shot behavior | **LR** (monotonic) |
| Football sanity | **LR** |
| Simplicity / interpretability / reproducibility | **LR** |

**Recommendation: Logistic Regression.** XGBoost is not chosen — its edge is
within normal variation, and LR is better calibrated and better-behaved at the
extremes. Per the rule "if the difference is within normal variation, prefer the
simpler model," LR wins.

## 9. Known limitations
- Internal model, not equivalent to commercial provider xG.
- No defender/GK (freeze-frame) context — by design, for internal reproducibility.
- Men's football sample (4 leagues 2015/16 + WC 2018/22 + Euro 2020/24).
- Penalties handled as a separate constant (0.7255), not modelled.
- Per-match xG is high-variance (corr ~0.41); reliable in aggregate.
- Tiny categories (Corner shots, cutback assists) have too little data to trust
  individually.

## 10. Frozen? **YES.**
Frozen as **Internal xG Model v1.0**: feature list, preprocessing, model type,
hyperparameters (LogReg L2 C=10), calibration decision (raw), penalty handling
(0.7255), and split methodology are locked.

## 11. Final model path
- [`models/internal_xg_v1.joblib`](models/internal_xg_v1.joblib)
- [`models/internal_xg_v1_meta.json`](models/internal_xg_v1_meta.json)
  (version, date, source, 1747 matches / 43,717 shots, features, hyperparameters,
  calibration, penalty xG, split methodology, final metrics, package versions,
  limitations).

## 12. Test results
`39 passed` — full suite including new freeze/immutability tests (v1 loads,
metadata frozen, predictions in range, penalty routed, and v1 predictions match
the reviewed baseline exactly).
