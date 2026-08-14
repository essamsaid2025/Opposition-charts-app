"""Embedded visual-evidence bridge (P3.1).

Turns a report's visual references into real chart images for export, using the
EXISTING Open Play visualization engine and the EXISTING evidence scoping. It stores
NO matplotlib figures — each chart is rendered once to PNG bytes (figure closed
immediately) and cached by scope signature so the same chart is never rendered twice.

    report + P0 insights  ->  plan_report_visuals()  ->  [VisualPlan(key, viz_hint, selections)]
                          ->  render_report_visuals(engine, frame)  ->  {key: png bytes}
                          ->  to_report_document(chart_images=...)  ->  PDF/HTML/PPTX

Scoping is identical to the corrected `_open_evidence` pathway: a player-specific
claim carries ``players=[name]`` and a match-specific claim carries the ``match`` — the
whole-team / whole-dataset map is never substituted for scoped evidence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class VisualPlan:
    key: str
    viz_hint: str
    selections: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"key": self.key, "viz_hint": self.viz_hint, "selections": dict(self.selections)}


def match_registry_viz(registry, hint: str, event_types=()) -> str | None:
    """Map a viz hint to an EXISTING registry visualization (shared with the Studio's
    _open_evidence). Falls back to an overview/heatmap, then the first registry viz."""
    tokens = [t for t in (hint or "").lower().split() if t]
    if tokens:
        for name in registry:
            if all(t in name.lower() for t in tokens):
                return name
    for et in event_types or ():
        for name in registry:
            if str(et).lower() in name.lower():
                return name
    for name in registry:
        if "heat" in name.lower() or "overview" in name.lower():
            return name
    return next(iter(registry), None)


def _scope_from_insight(by_id: dict, iid: str, base: dict) -> tuple[str, dict]:
    sel = dict(base)
    ins = by_id.get(iid)
    sv = getattr(ins, "supporting_viz", None) if ins else None
    if sv:
        if sv.event_types:
            sel["event_types"] = [e.lower() for e in sv.event_types]
        if sv.players:
            sel["players"] = list(sv.players)
    return (sv.viz_hint if sv else ""), sel


def plan_report_visuals(report, by_id: dict, base_selections: dict | None = None, *,
                        mode: str = "detailed", max_charts: int = 8) -> list[VisualPlan]:
    """Decide the SMALL set of high-value charts to embed and their exact scope. Pure —
    no engine needed, so scoping is unit-testable. Executive mode embeds fewer charts."""
    base = dict(base_selections or {})
    plans: list[VisualPlan] = []

    dna = (("progression", "final_third", "transitions", "recoveries") if mode == "detailed"
           else ("progression", "final_third"))
    for sid in dna:
        s = report.section(sid)
        if s and s.available and s.visual_key and s.evidence.insight_ids:
            hint, sel = _scope_from_insight(by_id, s.evidence.insight_ids[0], base)
            plans.append(VisualPlan(s.visual_key, hint or s.chart_hint, sel))

    # player-specific evidence — MUST stay scoped to the player, not the whole team
    if report.key_players and report.key_players[0].evidence.insight_ids:
        p = report.key_players[0]
        hint, sel = _scope_from_insight(by_id, p.evidence.insight_ids[0], base)
        sel["players"] = [p.name]
        plans.append(VisualPlan("players:primary", hint or "progress", sel))

    # vulnerability evidence (e.g. where the opponent loses possession)
    if report.vulnerabilities and report.vulnerabilities[0].evidence.insight_ids:
        v = report.vulnerabilities[0]
        hint, sel = _scope_from_insight(by_id, v.evidence.insight_ids[0], base)
        plans.append(VisualPlan("vulnerabilities:primary", hint or "turnover", sel))

    return plans[:max_charts]


def render_report_visuals(engine, frame, plans: list[VisualPlan], *, dpi: int = 150) -> dict[str, bytes]:
    """Render each plan to PNG bytes via the injected Open Play engine. Renders each
    unique (viz, scope) once; never stores a matplotlib figure."""
    if engine is None or frame is None or not plans:
        return {}
    import matplotlib.pyplot as plt

    themes = engine.metadata.get("themes", {}) if getattr(engine, "metadata", None) else {}
    vt = next(iter(themes.values()), {}) if themes else {}
    spec = engine.pitch_spec_cls()
    try:
        df_all = engine.apply_pitch_transforms(frame, spec)
    except Exception:
        df_all = frame
    out: dict[str, bytes] = {}
    cache: dict[str, bytes] = {}
    for pl in plans:
        viz = match_registry_viz(engine.viz_registry, pl.viz_hint, pl.selections.get("event_types", ()))
        if not viz:
            continue
        sig = json.dumps({"viz": viz, "sel": pl.selections}, sort_keys=True, default=str)
        if sig in cache:                             # render-once: reuse identical charts
            out[pl.key] = cache[sig]
            continue
        try:
            filtered = engine.apply_filters(frame, pl.selections)
            render_frame = engine.apply_pitch_transforms(filtered, spec)
            if render_frame is None or getattr(render_frame, "empty", True):
                continue
            ctx = engine.default_ctx(vt, spec, aux={"df_all": df_all}, title=viz)
            fig = engine.render(viz, render_frame, ctx)
            png = engine.export(fig, "png", dpi, False)
            plt.close(fig)                            # never keep the figure
        except Exception:
            continue
        cache[sig] = png
        out[pl.key] = png
    return out


def report_chart_images(engine, frame, report, by_id: dict, base_selections: dict | None = None, *,
                        mode: str = "detailed", dpi: int = 150) -> dict[str, bytes]:
    plans = plan_report_visuals(report, by_id, base_selections, mode=mode)
    return render_report_visuals(engine, frame, plans, dpi=dpi)
