"""The P0 tactical-insight rules.

Each rule is a pure function ``(ctx, th) -> Insight | None``. It reads the shared
:class:`InsightContext` aggregates (never re-scanning the frame), applies the
sample-size and effect-size safeguards from :class:`InsightThresholds`, and — only
when the evidence is sufficient — returns a structured :class:`Insight` with the
observation, interpretation and recommended investigation kept strictly separate.

Rules NEVER infer formations, pressing systems or player roles. They report what
the event distribution measured (observation), a cautious tactical reading of it
(interpretation), and what to look at next (recommendation).
"""
from __future__ import annotations

import pandas as pd

from fap.analytics.tactical.context import (
    CHANNEL_NAMES, InsightContext, channel_of, counts_and_total, event_ids,
)
from fap.analytics.tactical.model import (
    Confidence, Evidence, Insight, InsightCategory, Priority, SupportingViz,
)
from fap.analytics.tactical.thresholds import InsightThresholds, _clip01, grade

_LANE_LABELS = {"Left Lane": "left", "Central Lane": "central", "Right Lane": "right"}


# ------------------------------------------------------------------ helpers
def _leading(counts: dict[str, int], total: int) -> tuple[str, int, float, float]:
    """Return (name, count, share, margin_over_runner_up) for the top category."""
    if not counts or total <= 0:
        return "", 0, 0.0, 0.0
    ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    name, cnt = ordered[0]
    share = cnt / total
    second = ordered[1][1] / total if len(ordered) > 1 else 0.0
    return name, cnt, share, share - second


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _dominance_effect(share: float, margin: float, th: InsightThresholds) -> tuple[float, bool]:
    """Blend share-concentration and margin-over-runner-up into a 0-1 effect for
    confidence grading; also flag whether the pattern is 'strong'."""
    e_share = _clip01((share - th.dominance_share) / (th.strong_dominance_share - th.dominance_share))
    e_margin = _clip01((margin - th.min_effect_margin) / (th.strong_effect_margin - th.min_effect_margin))
    effect = _clip01(0.5 * e_share + 0.5 * e_margin)
    strong = share >= th.strong_dominance_share or margin >= th.strong_effect_margin
    return effect, strong


def _priority(level: Confidence, strong: bool) -> Priority:
    if level is Confidence.LOW:
        return Priority.LOW
    if level is Confidence.HIGH and strong:
        return Priority.HIGH
    return Priority.MEDIUM


def _y_lane(y: pd.Series) -> pd.Series:
    return pd.cut(y, bins=[-0.1, 33.33, 66.67, 100.1],
                  labels=["Left Lane", "Central Lane", "Right Lane"])


# ================================================================ Progression (1-5)
def _side_dominance(ctx: InsightContext, th: InsightThresholds, target_lane: str) -> Insight | None:
    prog = ctx.progressive
    if not ctx.caps["end_coords"] or len(prog) < th.min_progressive_actions:
        return None
    counts, total = counts_and_total(prog["lane"])
    name, cnt, share, margin = _leading(counts, total)
    if name != target_lane or share < th.dominance_share or margin < th.min_effect_margin:
        return None
    effect, strong = _dominance_effect(share, margin, th)
    level, cscore, _ = grade(total, th.min_progressive_actions, effect, ctx.quality, th)
    side = _LANE_LABELS[target_lane]
    others = {k: v for k, v in counts.items() if k != name}
    ev = [Evidence(f"Progressive actions", f"{total}", float(total)),
          Evidence(f"{target_lane}", _pct(share), share)]
    for lane in ("Left Lane", "Central Lane", "Right Lane"):
        if lane != target_lane:
            ev.append(Evidence(lane, _pct(counts.get(lane, 0) / total), counts.get(lane, 0) / total))
    return Insight(
        id=f"progression.{side}_dominance",
        category=InsightCategory.PROGRESSION,
        title=f"{side.capitalize()}-side progression is dominant",
        short_explanation=f"{_pct(share)} of progressive actions originate from the {side} corridor.",
        observation=(f"{_pct(share)} of {total} progressive actions started in the {side} corridor "
                     f"({target_lane}), ahead of the next corridor by {_pct(margin)}."),
        interpretation=(f"This indicates a strong {side}-sided progression preference in "
                        f"{ctx.subject}'s ball advancement."),
        recommendation=(f"Investigate {ctx.subject}'s {side} progression combinations — the players, "
                        f"passes and carries feeding this corridor."),
        evidence=tuple(ev), sample_size=total, confidence=level, confidence_score=cscore,
        priority=_priority(level, strong), subject=ctx.subject, event_ids=event_ids(prog),
        supporting_viz=SupportingViz(
            description=f"Progressive passes & carries in the {side} corridor",
            viz_hint="progress", event_types=("pass", "carry"), lane=target_lane),
        meta={"share": share, "margin": margin, "side": side, "lane": target_lane})


def rule_left_progression(ctx, th):   # 1
    return _side_dominance(ctx, th, "Left Lane")


def rule_right_progression(ctx, th):  # 2
    return _side_dominance(ctx, th, "Right Lane")


def rule_central_progression(ctx, th):  # 3
    return _side_dominance(ctx, th, "Central Lane")


def rule_progression_corridor(ctx: InsightContext, th: InsightThresholds) -> Insight | None:  # 4
    """Finer than the 3-lane side split: the dominant of five vertical corridors
    (wings / half-spaces / central)."""
    prog = ctx.progressive
    if not ctx.caps["end_coords"] or len(prog) < th.min_progressive_actions:
        return None
    counts, total = counts_and_total(channel_of(prog["y"]))
    name, cnt, share, margin = _leading(counts, total)
    if not name or share < th.dominance_share or margin < th.min_effect_margin:
        return None
    effect, strong = _dominance_effect(share, margin, th)
    level, cscore, _ = grade(total, th.min_progressive_actions, effect, ctx.quality, th)
    ev = [Evidence("Progressive actions", f"{total}", float(total)),
          Evidence(name, _pct(share), share)]
    ev += [Evidence(c, _pct(counts.get(c, 0) / total), counts.get(c, 0) / total)
           for c in CHANNEL_NAMES if c != name and counts.get(c, 0)]
    return Insight(
        id="progression.dominant_corridor",
        category=InsightCategory.PROGRESSION,
        title=f"Progression funnels through the {name.lower()}",
        short_explanation=f"{_pct(share)} of progressive actions run through the {name.lower()}.",
        observation=(f"Of {total} progressive actions, {_pct(share)} passed through the {name.lower()}, "
                     f"{_pct(margin)} clear of the next corridor."),
        interpretation=(f"{ctx.subject} shows a concentrated progression route through the {name.lower()} "
                        f"rather than spreading advancement across the pitch width."),
        recommendation=(f"Study how {ctx.subject} builds through the {name.lower()} and whether it can be "
                        f"congested to force play elsewhere."),
        evidence=tuple(ev), sample_size=total, confidence=level, confidence_score=cscore,
        priority=_priority(level, strong), subject=ctx.subject, event_ids=event_ids(prog),
        supporting_viz=SupportingViz(
            description=f"Progression map highlighting the {name.lower()}",
            viz_hint="progress", event_types=("pass", "carry")),
        meta={"share": share, "margin": margin, "channel": name})


def rule_progression_player(ctx: InsightContext, th: InsightThresholds) -> Insight | None:  # 5
    """The single player carrying the largest share of the team's progressive actions."""
    prog = ctx.progressive
    if not ctx.caps["players"] or not ctx.caps["end_coords"] or len(prog) < th.min_progressive_actions:
        return None
    counts, total = counts_and_total(prog["player"])
    name, cnt, share, margin = _leading(counts, total)
    if not name or cnt < th.min_player_actions or share < th.player_share:
        return None
    e_share = _clip01((share - th.player_share) / (th.strong_player_share - th.player_share))
    effect = _clip01(0.6 * e_share + 0.4 * _clip01(margin / th.strong_effect_margin))
    strong = share >= th.strong_player_share
    level, cscore, _ = grade(cnt, th.min_player_actions, effect, ctx.quality, th)
    return Insight(
        id="progression.primary_player",
        category=InsightCategory.PROGRESSION,
        title=f"{name} drives progression",
        short_explanation=f"{name} accounts for {_pct(share)} of progressive actions.",
        observation=(f"{name} made {cnt} of {total} progressive actions ({_pct(share)}), more than any "
                     f"other player."),
        interpretation=(f"{name} is a primary ball-progression outlet for {ctx.subject}."),
        recommendation=(f"Check where {name} receives and progresses from, and whether limiting their "
                        f"involvement disrupts {ctx.subject}'s advancement."),
        evidence=(Evidence("Progressive actions", f"{total}", float(total)),
                  Evidence(f"{name}", f"{cnt} ({_pct(share)})", share),
                  Evidence("Lead over next player", _pct(margin), margin)),
        sample_size=cnt, confidence=level, confidence_score=cscore,
        priority=_priority(level, strong), subject=name, event_ids=event_ids(prog[prog["player"] == name]),
        supporting_viz=SupportingViz(
            description=f"Progressive passes & carries by {name}",
            viz_hint="progress", event_types=("pass", "carry"), players=(name,)),
        meta={"player": name, "share": share})


# ================================================================ Final third (6-8)
def rule_final_third_entry_concentration(ctx: InsightContext, th: InsightThresholds) -> Insight | None:  # 6
    entries = ctx.final_third_entries
    if not ctx.caps["end_coords"] or len(entries) < th.min_final_third_entries:
        return None
    counts, total = counts_and_total(_y_lane(entries["y2"]))
    name, cnt, share, margin = _leading(counts, total)
    if not name or share < th.dominance_share or margin < th.min_effect_margin:
        return None
    effect, strong = _dominance_effect(share, margin, th)
    level, cscore, _ = grade(total, th.min_final_third_entries, effect, ctx.quality, th)
    side = _LANE_LABELS[name]
    ev = [Evidence("Final-third entries", f"{total}", float(total)), Evidence(name, _pct(share), share)]
    ev += [Evidence(l, _pct(counts.get(l, 0) / total), counts.get(l, 0) / total)
           for l in ("Left Lane", "Central Lane", "Right Lane") if l != name]
    return Insight(
        id="final_third.entry_concentration",
        category=InsightCategory.FINAL_THIRD,
        title=f"Final-third entries concentrate {side}",
        short_explanation=f"{_pct(share)} of final-third entries arrive through the {side} lane.",
        observation=(f"{_pct(share)} of {total} final-third entries crossed into the final third through "
                     f"the {side} lane."),
        interpretation=(f"{ctx.subject} tends to enter the final third down the {side}, rather than "
                        f"evenly across the pitch."),
        recommendation=(f"Investigate {ctx.subject}'s {side}-sided entry patterns and the defenders they "
                        f"attack when entering there."),
        evidence=tuple(ev), sample_size=total, confidence=level, confidence_score=cscore,
        priority=_priority(level, strong), subject=ctx.subject, event_ids=event_ids(entries),
        supporting_viz=SupportingViz(
            description=f"Passes & carries entering the final third ({side})",
            viz_hint="final third", event_types=("pass", "carry"), lane=name, third="Final Third"),
        meta={"share": share, "margin": margin, "side": side, "lane": name})


def rule_preferred_attacking_corridor(ctx: InsightContext, th: InsightThresholds) -> Insight | None:  # 7
    """The dominant of five corridors that final-third entries arrive through —
    finer than the side-lane concentration."""
    entries = ctx.final_third_entries
    if not ctx.caps["end_coords"] or len(entries) < th.min_final_third_entries:
        return None
    counts, total = counts_and_total(channel_of(entries["y2"]))
    name, cnt, share, margin = _leading(counts, total)
    if not name or share < th.dominance_share or margin < th.min_effect_margin:
        return None
    effect, strong = _dominance_effect(share, margin, th)
    level, cscore, _ = grade(total, th.min_final_third_entries, effect, ctx.quality, th)
    ev = [Evidence("Final-third entries", f"{total}", float(total)), Evidence(name, _pct(share), share)]
    ev += [Evidence(c, _pct(counts.get(c, 0) / total), counts.get(c, 0) / total)
           for c in CHANNEL_NAMES if c != name and counts.get(c, 0)]
    return Insight(
        id="final_third.preferred_corridor",
        category=InsightCategory.FINAL_THIRD,
        title=f"Preferred attacking corridor: {name.lower()}",
        short_explanation=f"{_pct(share)} of final-third entries use the {name.lower()}.",
        observation=(f"The {name.lower()} carried {_pct(share)} of {total} final-third entries, "
                     f"{_pct(margin)} more than the next corridor."),
        interpretation=(f"The {name.lower()} is {ctx.subject}'s preferred route into the final third."),
        recommendation=(f"Prepare for {ctx.subject}'s attacks arriving via the {name.lower()}; review the "
                        f"combinations that unlock it."),
        evidence=tuple(ev), sample_size=total, confidence=level, confidence_score=cscore,
        priority=_priority(level, strong), subject=ctx.subject, event_ids=event_ids(entries),
        supporting_viz=SupportingViz(
            description=f"Final-third entries via the {name.lower()}",
            viz_hint="final third", event_types=("pass", "carry"), third="Final Third"),
        meta={"share": share, "margin": margin, "channel": name})


def rule_box_entry_concentration(ctx: InsightContext, th: InsightThresholds) -> Insight | None:  # 8
    box = ctx.box_entries
    if not ctx.caps["end_coords"] or len(box) < th.min_box_entries:
        return None
    counts, total = counts_and_total(_y_lane(box["y2"]))
    name, cnt, share, margin = _leading(counts, total)
    if not name or share < th.dominance_share or margin < th.min_effect_margin:
        return None
    effect, strong = _dominance_effect(share, margin, th)
    level, cscore, _ = grade(total, th.min_box_entries, effect, ctx.quality, th)
    side = _LANE_LABELS[name]
    ev = [Evidence("Penalty-box entries", f"{total}", float(total)), Evidence(name, _pct(share), share)]
    ev += [Evidence(l, _pct(counts.get(l, 0) / total), counts.get(l, 0) / total)
           for l in ("Left Lane", "Central Lane", "Right Lane") if l != name]
    return Insight(
        id="final_third.box_entry_concentration",
        category=InsightCategory.FINAL_THIRD,
        title=f"Box entries favour the {side}",
        short_explanation=f"{_pct(share)} of penalty-box entries arrive from the {side}.",
        observation=(f"{_pct(share)} of {total} penalty-box entries arrived from the {side} side."),
        interpretation=(f"{ctx.subject} delivers into the box predominantly from the {side}."),
        recommendation=(f"Investigate {ctx.subject}'s {side}-sided box deliveries (crosses, cut-backs) and "
                        f"the runners attacking them."),
        evidence=tuple(ev), sample_size=total, confidence=level, confidence_score=cscore,
        priority=_priority(level, strong), subject=ctx.subject, event_ids=event_ids(box),
        supporting_viz=SupportingViz(
            description=f"Entries into the penalty area ({side})",
            viz_hint="box", event_types=("pass", "cross", "carry"), lane=name),
        meta={"share": share, "margin": margin, "side": side, "lane": name})


# ================================================================ Recoveries (9-10)
def rule_recovery_zone(ctx: InsightContext, th: InsightThresholds) -> Insight | None:  # 9
    rec = ctx.recoveries
    if not ctx.caps["recovery_events"] or len(rec) < th.min_recoveries:
        return None
    zone = rec["start_third"].astype(str) + " · " + rec["lane"].astype(str)
    counts, total = counts_and_total(zone)
    name, cnt, share, margin = _leading(counts, total)
    if not name or "nan" in name.lower() or share < th.dominance_share or margin < th.min_effect_margin:
        return None
    effect, strong = _dominance_effect(share, margin, th)
    level, cscore, _ = grade(total, th.min_recoveries, effect, ctx.quality, th)
    return Insight(
        id="recoveries.dominant_zone",
        category=InsightCategory.RECOVERIES,
        title=f"Ball recoveries concentrate in the {name.lower()}",
        short_explanation=f"{_pct(share)} of ball recoveries occur in the {name.lower()}.",
        observation=(f"{_pct(share)} of {total} ball recoveries occurred in the {name} zone."),
        interpretation=(f"{ctx.subject} regains possession most often in the {name.lower()}."),
        recommendation=(f"Investigate why recoveries cluster in the {name.lower()} — the trigger and the "
                        f"players involved."),
        evidence=(Evidence("Ball recoveries", f"{total}", float(total)),
                  Evidence(name, _pct(share), share),
                  Evidence("Lead over next zone", _pct(margin), margin)),
        sample_size=total, confidence=level, confidence_score=cscore,
        priority=_priority(level, strong), subject=ctx.subject, event_ids=event_ids(rec),
        supporting_viz=SupportingViz(
            description=f"Ball recoveries in the {name.lower()}",
            viz_hint="recovery", event_types=("recovery", "interception", "tackle")),
        meta={"share": share, "margin": margin, "zone": name})


def rule_high_recovery_concentration(ctx: InsightContext, th: InsightThresholds) -> Insight | None:  # 10
    rec = ctx.recoveries
    if not ctx.caps["recovery_events"] or not ctx.caps["coords"] or len(rec) < th.min_recoveries:
        return None
    total = int(len(rec))
    high = int((rec["x"] >= 66.67).sum())
    share = high / total if total else 0.0
    if share < th.high_recovery_share:
        return None
    effect = _clip01((share - th.high_recovery_share) / (th.strong_recovery_share - th.high_recovery_share))
    strong = share >= th.strong_recovery_share
    level, cscore, _ = grade(total, th.min_recoveries, effect, ctx.quality, th)
    return Insight(
        id="recoveries.high_concentration",
        category=InsightCategory.RECOVERIES,
        title="High ball-recovery concentration",
        short_explanation=f"{_pct(share)} of recoveries occur in the final third.",
        observation=(f"{high} of {total} ball recoveries ({_pct(share)}) occurred in the final third "
                     f"(attacking third of the pitch)."),
        interpretation=(f"{ctx.subject} wins the ball back high up the pitch relatively often. Note: this "
                        f"reflects recovery locations only, not a measured pressing intensity."),
        recommendation=(f"Investigate {ctx.subject}'s high recoveries and whether they convert into "
                        f"immediate attacking situations."),
        evidence=(Evidence("Ball recoveries", f"{total}", float(total)),
                  Evidence("Final-third recoveries", f"{high} ({_pct(share)})", share)),
        sample_size=total, confidence=level, confidence_score=cscore,
        priority=_priority(level, strong), subject=ctx.subject, event_ids=event_ids(rec[rec["x"] >= 66.67]),
        supporting_viz=SupportingViz(
            description="Ball recoveries in the final third",
            viz_hint="recovery", event_types=("recovery", "interception", "tackle"),
            third="Final Third"),
        meta={"share": share})


# ================================================================ Players (11-12)
def rule_primary_final_third_progressor(ctx: InsightContext, th: InsightThresholds) -> Insight | None:  # 11
    """The player creating the most entries into the final third — the team's
    primary outlet into dangerous areas (distinct from the overall progressor)."""
    entries = ctx.final_third_entries
    if not ctx.caps["players"] or not ctx.caps["end_coords"] or len(entries) < th.min_final_third_entries:
        return None
    counts, total = counts_and_total(entries["player"])
    name, cnt, share, margin = _leading(counts, total)
    if not name or cnt < th.min_player_actions or share < th.player_share:
        return None
    e_share = _clip01((share - th.player_share) / (th.strong_player_share - th.player_share))
    effect = _clip01(0.6 * e_share + 0.4 * _clip01(margin / th.strong_effect_margin))
    strong = share >= th.strong_player_share
    level, cscore, _ = grade(cnt, th.min_player_actions, effect, ctx.quality, th)
    return Insight(
        id="players.primary_final_third_progressor",
        category=InsightCategory.PLAYERS,
        title=f"{name} is the primary final-third outlet",
        short_explanation=f"{name} makes {_pct(share)} of final-third entries.",
        observation=(f"{name} produced {cnt} of {total} final-third entries ({_pct(share)}), the most of "
                     f"any player."),
        interpretation=(f"{name} is {ctx.subject}'s main route into the final third."),
        recommendation=(f"Investigate {name}'s entry patterns and whether denying them the ball slows "
                        f"{ctx.subject}'s final-third access."),
        evidence=(Evidence("Final-third entries", f"{total}", float(total)),
                  Evidence(f"{name}", f"{cnt} ({_pct(share)})", share),
                  Evidence("Lead over next player", _pct(margin), margin)),
        sample_size=cnt, confidence=level, confidence_score=cscore,
        priority=_priority(level, strong), subject=name,
        event_ids=event_ids(entries[entries["player"] == name]),
        supporting_viz=SupportingViz(
            description=f"Final-third entries by {name}",
            viz_hint="final third", event_types=("pass", "carry"), players=(name,),
            third="Final Third"),
        meta={"player": name, "share": share})


def rule_primary_attacking_involvement(ctx: InsightContext, th: InsightThresholds) -> Insight | None:  # 12
    """The player most involved in attacking actions (touches/actions in the final
    third + box entries + shots)."""
    if not ctx.caps["players"] or not ctx.caps["coords"]:
        return None
    df = ctx.df
    etype = df["event_type"].astype(str).str.lower()
    attacking = df[(df["start_third"].astype(str) == "Final Third")
                   | df["into_box"].fillna(False).astype(bool)
                   | etype.eq("shot")]
    counts, total = counts_and_total(attacking["player"])
    if total < th.min_final_third_entries:
        return None
    name, cnt, share, margin = _leading(counts, total)
    if not name or cnt < th.min_player_actions or share < th.player_share:
        return None
    e_share = _clip01((share - th.player_share) / (th.strong_player_share - th.player_share))
    effect = _clip01(0.6 * e_share + 0.4 * _clip01(margin / th.strong_effect_margin))
    strong = share >= th.strong_player_share
    level, cscore, _ = grade(cnt, th.min_player_actions, effect, ctx.quality, th)
    return Insight(
        id="players.primary_attacking_involvement",
        category=InsightCategory.PLAYERS,
        title=f"{name} leads attacking involvement",
        short_explanation=f"{name} takes part in {_pct(share)} of final-third attacking actions.",
        observation=(f"{name} was involved in {cnt} of {total} attacking actions in and around the final "
                     f"third ({_pct(share)}), the most of any player."),
        interpretation=(f"{name} is central to {ctx.subject}'s attacking play in dangerous areas."),
        recommendation=(f"Investigate {name}'s attacking involvement and the zones where they are most "
                        f"active."),
        evidence=(Evidence("Attacking actions", f"{total}", float(total)),
                  Evidence(f"{name}", f"{cnt} ({_pct(share)})", share),
                  Evidence("Lead over next player", _pct(margin), margin)),
        sample_size=cnt, confidence=level, confidence_score=cscore,
        priority=_priority(level, strong), subject=name,
        event_ids=event_ids(attacking[attacking["player"] == name]),
        supporting_viz=SupportingViz(
            description=f"Attacking actions by {name} in the final third",
            viz_hint="touch", event_types=(), players=(name,), third="Final Third"),
        meta={"player": name, "share": share})


# ================================================================ Transitions (P2)
def rule_recovery_to_progression(ctx: InsightContext, th: InsightThresholds) -> Insight | None:
    rt = ctx.rec_transitions
    if rt.empty or len(rt) < th.min_transition_recoveries:
        return None
    total = len(rt)
    n_prog = int(rt["led_prog"].sum())
    share = n_prog / total
    if share < th.transition_share:
        return None
    counts, ptot = counts_and_total(rt.loc[rt["led_prog"], "prog_lane"])
    dname, _dc, dshare, _dm = _leading(counts, ptot)
    dir_txt = ""
    if dname in _LANE_LABELS and dshare >= th.dominance_share:
        dir_txt = f", most often down the {_LANE_LABELS[dname]}"
    effect = _clip01((share - th.transition_share) / (th.strong_transition_share - th.transition_share))
    strong = share >= th.strong_transition_share
    level, cscore, _ = grade(total, th.min_transition_recoveries, effect, ctx.quality, th)
    ev = [Evidence("Ball recoveries", f"{total}", float(total)),
          Evidence("Recoveries → progression", f"{n_prog} ({_pct(share)})", share)]
    if dname:
        ev.append(Evidence("Main direction", f"{dname} ({_pct(dshare)})", dshare))
    return Insight(
        id="transitions.recovery_to_progression",
        category=InsightCategory.TRANSITIONS,
        title="Progresses after regaining possession",
        short_explanation=f"{_pct(share)} of ball recoveries are followed by progression{dir_txt}.",
        observation=(f"{n_prog} of {total} ball recoveries ({_pct(share)}) were followed by a "
                     f"progressive action in the same possession{dir_txt}."),
        interpretation=f"{ctx.subject} looks to progress the ball soon after regaining it.",
        recommendation=(f"Investigate {ctx.subject}'s transition progression and whether the first action "
                        f"after a recovery can be pressed."),
        evidence=tuple(ev), sample_size=total, confidence=level, confidence_score=cscore,
        priority=_priority(level, strong), subject=ctx.subject, event_ids=event_ids(ctx.recoveries),
        supporting_viz=SupportingViz(description="Ball recoveries and the progression that follows",
                                     viz_hint="recovery",
                                     event_types=("recovery", "interception", "tackle")),
        meta={"share": share, "direction": dname})


def rule_recovery_to_final_third(ctx: InsightContext, th: InsightThresholds) -> Insight | None:
    rt = ctx.rec_transitions
    if rt.empty:
        return None
    eligible = rt[rt["rec_third"] != "Final Third"]      # only recoveries that can ENTER the final third
    n = len(eligible)
    if n < th.min_transition_recoveries:
        return None
    n_ft = int(eligible["led_ft"].sum())
    share = n_ft / n
    if share < th.transition_share:
        return None
    rapid_txt = ""
    if ctx.speed_available:
        delays = eligible.loc[eligible["led_ft"], "delay_s"].dropna()
        if len(delays):
            rapid = float((delays <= th.rapid_transition_seconds).mean())
            rapid_txt = f" — {_pct(rapid)} within {int(th.rapid_transition_seconds)}s"
    effect = _clip01((share - th.transition_share) / (th.strong_transition_share - th.transition_share))
    strong = share >= th.strong_transition_share
    level, cscore, _ = grade(n, th.min_transition_recoveries, effect, ctx.quality, th)
    verb = "rapid progression into" if ctx.speed_available else "progression into"
    return Insight(
        id="transitions.recovery_to_final_third",
        category=InsightCategory.TRANSITIONS,
        title="Recoveries lead to final-third progression",
        short_explanation=f"{_pct(share)} of recoveries outside the final third are followed by "
                          f"final-third progression{rapid_txt}.",
        observation=(f"{n_ft} of {n} recoveries made outside the final third ({_pct(share)}) were "
                     f"followed by {verb} the final third{rapid_txt}."),
        interpretation=f"{ctx.subject} turns recoveries into forward progression rather than recycling "
                       f"possession.",
        recommendation=f"Investigate {ctx.subject}'s recovery-to-attack transitions and the players who "
                       f"carry them forward.",
        evidence=(Evidence("Recoveries (outside final third)", f"{n}", float(n)),
                  Evidence("→ final-third progression", f"{n_ft} ({_pct(share)})", share)),
        sample_size=n, confidence=level, confidence_score=cscore, priority=_priority(level, strong),
        subject=ctx.subject, event_ids=event_ids(ctx.recoveries),
        supporting_viz=SupportingViz(description="Recoveries that lead into the final third",
                                     viz_hint="recovery",
                                     event_types=("recovery", "interception", "tackle")),
        meta={"share": share, "rapid_available": ctx.speed_available})


def rule_recovery_to_shot(ctx: InsightContext, th: InsightThresholds) -> Insight | None:
    rt = ctx.rec_transitions
    if rt.empty or len(rt) < th.min_transition_recoveries:
        return None
    total = len(rt)
    n_shot = int(rt["led_shot"].sum())
    if n_shot < th.min_transition_shots:            # low-sample guard: no claim from a handful
        return None
    share = n_shot / total
    if share < 0.08:
        return None
    effect = _clip01(share / 0.25)
    level, cscore, _ = grade(total, th.min_transition_recoveries, effect, ctx.quality, th)
    return Insight(
        id="transitions.recovery_to_shot",
        category=InsightCategory.TRANSITIONS,
        title="Recoveries can lead to shots",
        short_explanation=f"{n_shot} of {total} recoveries ({_pct(share)}) led to a shot in the same "
                          f"possession.",
        observation=f"{n_shot} of {total} ball recoveries ({_pct(share)}) were followed by a shot within "
                    f"the same possession.",
        interpretation=f"{ctx.subject} occasionally generates shots directly from transitions.",
        recommendation="Investigate these recovery-to-shot sequences and the recovery zones that feed them.",
        evidence=(Evidence("Ball recoveries", f"{total}", float(total)),
                  Evidence("→ shot", f"{n_shot} ({_pct(share)})", share)),
        sample_size=total, confidence=level, confidence_score=cscore, priority=Priority.MEDIUM,
        subject=ctx.subject, event_ids=event_ids(ctx.recoveries),
        supporting_viz=SupportingViz(description="Recoveries that lead to shots", viz_hint="recovery",
                                     event_types=("recovery", "interception", "tackle")),
        meta={"share": share})


def rule_transition_direction(ctx: InsightContext, th: InsightThresholds) -> Insight | None:
    rt = ctx.rec_transitions
    prog = rt[rt["led_prog"]] if not rt.empty else rt
    if prog.empty or len(prog) < th.min_transition_recoveries:
        return None
    counts, total = counts_and_total(prog["prog_lane"])
    name, cnt, share, margin = _leading(counts, total)
    if name not in _LANE_LABELS or share < th.dominance_share or margin < th.min_effect_margin:
        return None
    side = _LANE_LABELS[name]
    effect, strong = _dominance_effect(share, margin, th)
    level, cscore, _ = grade(total, th.min_transition_recoveries, effect, ctx.quality, th)
    return Insight(
        id="transitions.direction",
        category=InsightCategory.TRANSITIONS,
        title=f"Transitions break to the {side}",
        short_explanation=f"{_pct(share)} of post-recovery progression goes through the {side}.",
        observation=f"When {ctx.subject} progresses after a recovery, {_pct(share)} of the time it goes "
                    f"through the {side} ({name}).",
        interpretation=f"{ctx.subject}'s transitions are channelled to the {side}.",
        recommendation=f"Investigate the {side}-sided outlet {ctx.subject} uses in transition.",
        evidence=(Evidence("Post-recovery progressions", f"{total}", float(total)),
                  Evidence(name, _pct(share), share)),
        sample_size=total, confidence=level, confidence_score=cscore, priority=_priority(level, strong),
        subject=ctx.subject, event_ids=event_ids(ctx.recoveries),
        supporting_viz=SupportingViz(description=f"Post-recovery progression via the {side}",
                                     viz_hint="recovery",
                                     event_types=("recovery", "interception", "tackle")),
        meta={"share": share, "side": side})


# ================================================================ Turnovers / Vulnerabilities (P2)
def rule_turnover_zone(ctx: InsightContext, th: InsightThresholds) -> Insight | None:
    to = ctx.turnovers
    if to.empty or len(to) < th.min_turnovers or not ctx.caps["coords"]:
        return None
    zone = to["start_third"].astype(str) + " · " + to["lane"].astype(str)
    counts, total = counts_and_total(zone)
    name, cnt, share, margin = _leading(counts, total)
    if not name or "nan" in name.lower() or share < th.turnover_zone_share or margin < th.min_effect_margin:
        return None
    effect = _clip01((share - th.turnover_zone_share) / (0.60 - th.turnover_zone_share))
    strong = share >= 0.55
    level, cscore, _ = grade(total, th.min_turnovers, effect, ctx.quality, th)
    return Insight(
        id="vulnerability.turnover_zone",
        category=InsightCategory.VULNERABILITY,
        title=f"Loses possession most in the {name.lower()}",
        short_explanation=f"{_pct(share)} of possession losses occur in the {name.lower()}.",
        observation=f"{cnt} of {total} possession losses ({_pct(share)}) occurred in the {name} zone.",
        interpretation=(f"This area may represent a potential pressure opportunity against {ctx.subject}. "
                        f"It reflects where they lose the ball, not a confirmed weakness."),
        recommendation=f"Investigate the triggers of {ctx.subject}'s losses in the {name.lower()} and "
                       f"whether this zone can be targeted.",
        evidence=(Evidence("Possession losses", f"{total}", float(total)),
                  Evidence(name, _pct(share), share),
                  Evidence("Lead over next zone", _pct(margin), margin)),
        sample_size=total, confidence=level, confidence_score=cscore, priority=_priority(level, strong),
        subject=ctx.subject, event_ids=event_ids(to),
        supporting_viz=SupportingViz(description=f"Possession losses in the {name.lower()}",
                                     viz_hint="turnover"),
        meta={"share": share, "zone": name})


def rule_route_failure(ctx: InsightContext, th: InsightThresholds) -> Insight | None:
    """A dominant movement route whose loss RATE (turnovers / attempts through it) is
    high — a corridor they favour but repeatedly give the ball away in. Rate vs a real
    denominator, never raw turnover count."""
    mov, to = ctx.movement, ctx.turnovers
    if mov.empty or to.empty or not ctx.caps["coords"]:
        return None
    att_counts, att_total = counts_and_total(mov["lane"])
    to_counts, _ = counts_and_total(to["lane"])
    name, attempts, ashare, _m = _leading(att_counts, att_total)
    if not name or attempts < th.min_route_attempts:
        return None
    losses = to_counts.get(name, 0)
    rate = losses / attempts if attempts else 0.0
    if rate < th.high_turnover_rate:
        return None
    side = _LANE_LABELS.get(name, name.lower())
    effect = _clip01((rate - th.high_turnover_rate) / (th.strong_turnover_rate - th.high_turnover_rate))
    strong = rate >= th.strong_turnover_rate
    level, cscore, _ = grade(attempts, th.min_route_attempts, effect, ctx.quality, th)
    return Insight(
        id="vulnerability.route_failure",
        category=InsightCategory.VULNERABILITY,
        title=f"High losses along the favoured {side} route",
        short_explanation=f"{_pct(rate)} of actions through the {side} corridor end in a turnover.",
        observation=(f"The {side} corridor carries the most actions ({attempts}), but {losses} of them "
                     f"({_pct(rate)}) end in a possession loss."),
        interpretation=(f"{ctx.subject} favours the {side} corridor yet gives the ball away there often; "
                        f"this route may be contestable."),
        recommendation=f"Investigate whether congesting the {side} corridor forces more {ctx.subject} losses.",
        evidence=(Evidence(f"Actions through {name}", f"{attempts}", float(attempts)),
                  Evidence("Losses there", f"{losses} ({_pct(rate)})", rate)),
        sample_size=attempts, confidence=level, confidence_score=cscore, priority=_priority(level, strong),
        subject=ctx.subject, event_ids=event_ids(to),
        supporting_viz=SupportingViz(description=f"Turnovers along the {side} corridor", viz_hint="turnover",
                                     lane=name),
        meta={"rate": rate, "lane": name, "side": side})


def rule_final_third_inefficiency(ctx: InsightContext, th: InsightThresholds) -> Insight | None:
    ft = len(ctx.final_third_entries)
    if ft < th.min_ft_for_efficiency or not ctx.caps["end_coords"]:
        return None
    box = len(ctx.box_entries)
    shots = int(ctx.df["event_type"].astype(str).str.lower().eq("shot").sum())
    box_conv, shot_conv = box / ft, shots / ft
    low_box = box_conv < th.low_box_conversion
    low_shot = shot_conv < th.low_shot_conversion
    if not (low_box or low_shot):
        return None
    if low_box:
        detail = f"only {box} box entries from {ft} final-third entries ({_pct(box_conv)})"
        gap, floor = box_conv, th.low_box_conversion
    else:
        detail = f"only {shots} shots from {ft} final-third entries ({_pct(shot_conv)})"
        gap, floor = shot_conv, th.low_shot_conversion
    effect = _clip01((floor - gap) / max(0.01, floor))
    level, cscore, _ = grade(ft, th.min_ft_for_efficiency, effect, ctx.quality, th)
    return Insight(
        id="vulnerability.final_third_inefficiency",
        category=InsightCategory.VULNERABILITY,
        title="Final-third entries rarely become chances",
        short_explanation=f"Final-third entries convert poorly: {detail}.",
        observation=f"{ctx.subject} made {ft} final-third entries but {detail}.",
        interpretation=(f"{ctx.subject} enters the final third without consistently creating box entries or "
                        f"shots; their final-third play may be containable."),
        recommendation=f"Investigate whether {ctx.subject} can be forced wide/backwards once they reach the "
                       f"final third.",
        evidence=(Evidence("Final-third entries", f"{ft}", float(ft)),
                  Evidence("Box entries", f"{box} ({_pct(box_conv)})", box_conv),
                  Evidence("Shots", f"{shots} ({_pct(shot_conv)})", shot_conv)),
        sample_size=ft, confidence=level, confidence_score=cscore, priority=_priority(level, False),
        subject=ctx.subject, event_ids=event_ids(ctx.final_third_entries),
        supporting_viz=SupportingViz(description="Final-third entries vs box entries / shots",
                                     viz_hint="final third", event_types=("pass", "carry"),
                                     third="Final Third"),
        meta={"box_conversion": box_conv, "shot_conversion": shot_conv})


# ---- ordered registry of the rules (P0 + P2) ----
RULES = (
    rule_left_progression, rule_right_progression, rule_central_progression,
    rule_progression_corridor, rule_progression_player,
    rule_final_third_entry_concentration, rule_preferred_attacking_corridor,
    rule_box_entry_concentration,
    rule_recovery_zone, rule_high_recovery_concentration,
    rule_primary_final_third_progressor, rule_primary_attacking_involvement,
    # P2 — transitions
    rule_recovery_to_progression, rule_recovery_to_final_third, rule_recovery_to_shot,
    rule_transition_direction,
    # P2 — turnovers / vulnerabilities
    rule_turnover_zone, rule_route_failure, rule_final_third_inefficiency,
)
