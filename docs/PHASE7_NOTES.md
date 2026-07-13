# Phase 7 — Production Visualization Engine (v4)

## Scope delivered (additive over v3, all 17 v3 chart names preserved)
- **Plugin registry**: `register_viz()` / `VIZ_REGISTRY`; category-grouped picker; new plugins never modify existing code.
- **Pitch Engine**: `PitchSpec` — Horizontal/Vertical/Auto, 9 views (halves, thirds, penalty areas, custom crop), mirror/flip X, flip Y, stripes; single coordinate pipeline (`apply_pitch_transforms` → `pc()`), no distortion in either orientation.
- **Thirds Engine**: 10 modes (lines, lanes, combined, 5 highlights, custom positions), color/width/alpha/labels, orientation-aware, correct z-order (1.5–2.6, under content).
- **Visualization Themes (16)**: Opta Analyst, The Athletic, StatsBomb, Hudl, Wyscout, FBref, SofaScore, UEFA, FIFA, TV Broadcast, Presentation, Print, Dark/Light Professional, Club, Custom. Figures only — Streamlit chrome untouched (separate APP_THEMES).
- **Heatmap Studio**: 9 genuinely distinct types (Gaussian/Adaptive KDE, smooth density, grid w/ cell labels, hexbin count/mean, zone thirds×lanes / custom grid, classic histogram) × 10 semantic presets; bandwidth, levels, interpolation, cmap, threshold percentile, cell size, normalization, percentile scale, log scale. NumPy-only blur — no scipy added.
- **Marker Studio**: 10 shapes, size/border/fill/opacity/rotation/jitter/z-order, shadow + glow effects.
- **Arrow Studio**: Straight/Curved/Bezier/Dashed/Dotted/Double/Comet/Gradient Comet; width, head, curvature, opacity, cap/join, shadow/glow.
- **Label Engine**: renderer-based collision detection, 9 candidate positions, halo, box, leader lines, rotation, hide-overlapping, max labels.
- **Legend Engine**: 8 positions (incl. outside), orientation, frame, title, rename/hide/custom order.
- **Tables**: Athletic-style stat table — metric/value/rank/percentile mini-bars, zebra rows, conditional formatting (16 metrics vs per-match distribution).
- **Match Summary Cards**: 12 metrics, ▲▼ delta vs other-match average, per-card sparkline.
- **Dashboard Builder**: 8 preset dashboards (Match Summary, Team, Opponent, Player, GK, Shot Quality, Territory, Performance) + Custom Dashboard (pick 4 panels + cards row), templates saved in session and via JSON download/upload.
- **Export**: PNG/SVG/PDF, DPI 100–400, saved from the same figure object with identical facecolor → matches preview.
- **Z-order ladder**: stripes 1 < highlights 1.5 < pitch lines 2 < heat 2.2 < thirds lines 2.5 < arrows 4 < markers 6 < zone text 7 < seq numbers 8 < labels 9+.

## Fixes vs v3 issue list
Thirds correct in both orientations; overlays crop-safe; consistent vertical mapping via one `pc()` helper; unified Legend Engine; collision-aware labels always above markers; single theme token source; heatmap types now visually distinct; arrows no longer hidden behind markers (z-order ladder); export = preview.

## Verification
- `FAP_TEST=1 python test_phase7.py` → **PASSED: 160 FAILED: 0** (every plugin × both orientations, 9 views, 10 thirds modes, 9 heat types + 10 presets × 2 orientations, 8 arrow kinds, 10 marker shapes, 14 themes on dashboards, 4 sequence modes, 3 export formats, empty-dataframe safety).
- Headless boot: `streamlit run app.py --server.headless true` → `/_stcore/health` = 200, zero exceptions in log (Streamlit 1.59.1, mplsoccer 1.6.1, matplotlib 3.10.8, pandas 3.0.2, numpy 2.4.4).
- `requirements.txt` unchanged — no new dependencies.

## Files
`app.py` (2,099 lines) · `test_phase7.py` · `requirements.txt` · `sample_open_play_data.csv` · `renders/` (3 proof images)
