"""Platform display-configuration layer (presentation-only, capability-gated).

This module sits AFTER analytical calculation in the pipeline:

    Dataset -> filters -> metric/calculation -> visualization frame
            -> visualization spec -> **display configuration** -> renderer

A ``DisplayConfig`` never changes data, filters, coordinates or calculations — it
only toggles what is *drawn* (values, legend, labels, xG encoding, xG numbers,
outcome split, zones, density, grid, axes, annotations). Every toggle's default
reproduces the platform's current output, so an unconfigured visualization looks
exactly as it does today (backward compatible).

A ``VisualizationCapabilities`` declares which toggles are *meaningful* for a given
visualization, so the UI renders ONLY the relevant controls (strict capability
gating): no "Show xG" on a passing map, no "Show density" on a bar chart. The two
rendering systems in the platform both consume this:

* ``fap.visuals`` plugins declare capabilities and pull the matching controls into
  their declarative control set (``display_controls_for``);
* the locked Open Play engine gets capabilities inferred by category
  (``fap.openplay.viz_descriptors``) and the UI maps toggles onto the engine's
  existing ctx keys — never changing the engine.

Pure: no Streamlit, no matplotlib, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from fap.core.types import Control

# ---------------------------------------------------------------- canonical toggles
# Each capability maps to ONE display control key. Some keys already exist in the
# platform's control groups (legend/show_labels/show_zone_overlay/show_grid) and are
# reused verbatim; the rest are new presentation toggles defined below. Defaults are
# chosen so the *current* rendered output is unchanged.
CAP_TO_KEY: dict[str, str] = {
    "values": "show_values",
    "legend": "legend",
    "labels": "show_labels",
    "player_names": "show_player_names",
    "event_counts": "show_event_counts",
    "percentages": "show_percentages",
    "xg": "show_xg",
    "xg_values": "show_xg_values",
    "outcome": "show_outcome",
    "zones": "show_zone_overlay",
    "density": "show_density",
    "grid": "show_grid",
    "axes": "show_axes",
    "annotations": "show_annotations",
}

# New presentation controls owned by this module (checkbox toggles). Existing keys
# (legend/show_labels/show_zone_overlay/show_grid) are pulled from CONTROL_GROUPS so
# there is a single definition of each.
# Every display control key (the presentation-only surface). The generic styling
# control renderer excludes these so a toggle is never rendered twice (once in the
# capability-gated Display panel and once in styling) — that would fight over the
# same key. Presentation lives in the Display panel; styling stays in Controls.
DISPLAY_KEYS: frozenset[str] = frozenset(CAP_TO_KEY.values())

_NEW_CONTROLS: dict[str, Control] = {
    # default OFF: no visualization prints values today, so an unconfigured chart is
    # unchanged; a viz that opts into `values` can raise its own default (see below).
    "show_values": Control("show_values", "Show values", "checkbox", default=False,
                           help="Numeric values printed on the marks."),
    "show_player_names": Control("show_player_names", "Show player names", "checkbox",
                                 default=False),
    "show_event_counts": Control("show_event_counts", "Show event counts", "checkbox",
                                 default=False),
    "show_percentages": Control("show_percentages", "Show percentages", "checkbox",
                                default=True),
    "show_xg": Control("show_xg", "Show xG", "checkbox", default=True,
                       help="xG visual encoding (marker size/colour). Off hides the "
                            "encoding only — the xG calculation is untouched."),
    "show_xg_values": Control("show_xg_values", "Show xG values", "checkbox", default=False,
                              help="Print the numeric xG next to each shot."),
    "show_outcome": Control("show_outcome", "Show outcome", "checkbox", default=True,
                            help="Colour marks by successful/unsuccessful outcome."),
    "show_density": Control("show_density", "Show density", "checkbox", default=True),
    "show_axes": Control("show_axes", "Show axes", "checkbox", default=True),
    "show_annotations": Control("show_annotations", "Show annotations", "checkbox",
                                default=True),
}


def _control_for_key(key: str) -> Control:
    if key in _NEW_CONTROLS:
        return _NEW_CONTROLS[key]
    # existing keys live in the platform's control groups
    from fap.visuals.controls import CONTROL_GROUPS
    for group in CONTROL_GROUPS.values():
        for control in group:
            if control.key == key:
                return control
    # last resort: a plain checkbox default True
    return Control(key, key.replace("_", " ").title(), "checkbox", default=True)


# ---------------------------------------------------------------- capabilities
@dataclass(frozen=True, slots=True)
class VisualizationCapabilities:
    """Which display toggles a visualization can meaningfully honour. All default
    False except the near-universal ones (legend/annotations), so a visualization
    opts in only to what it actually supports — the UI shows nothing more."""
    values: bool = False
    legend: bool = True
    labels: bool = False
    player_names: bool = False
    event_counts: bool = False
    percentages: bool = False
    xg: bool = False
    xg_values: bool = False
    outcome: bool = False
    zones: bool = False
    density: bool = False
    grid: bool = False
    axes: bool = False
    annotations: bool = True

    def supported(self) -> tuple[str, ...]:
        """Capability names this visualization supports, in a stable order."""
        return tuple(f.name for f in fields(self) if getattr(self, f.name))

    def control_keys(self) -> tuple[str, ...]:
        """The display control keys applicable to this visualization (strict gate)."""
        return tuple(CAP_TO_KEY[name] for name in self.supported() if name in CAP_TO_KEY)

    def controls(self) -> tuple[Control, ...]:
        """Declarative Control objects for exactly the supported toggles."""
        return tuple(_control_for_key(k) for k in self.control_keys())

    def to_dict(self) -> dict[str, bool]:
        return {f.name: bool(getattr(self, f.name)) for f in fields(self)}


def display_controls_for(caps: VisualizationCapabilities) -> tuple[Control, ...]:
    """The capability-gated set of display controls for a visualization."""
    return caps.controls()


def display_defaults(caps: VisualizationCapabilities | None = None,
                     overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Default value for every display key (optionally only the supported ones).
    These defaults reproduce the platform's current output. ``overrides`` lets a
    specific visualization raise a default it genuinely ships on (e.g. a chart that
    draws a grid by default → ``{"show_grid": True}``) without changing the global
    baseline any other visualization sees."""
    keys = caps.control_keys() if caps is not None else tuple(CAP_TO_KEY.values())
    ov = overrides or {}
    return {k: ov.get(k, _control_for_key(k).default) for k in dict.fromkeys(keys)}


def reset_display(controls: dict[str, Any],
                  caps: VisualizationCapabilities | None = None,
                  overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Restore display toggles to their defaults WITHOUT touching any other control
    (dataset/player/team/match/analytical filters, theme, marker sizes, …). Mutates
    and returns ``controls`` for convenience."""
    for key, default in display_defaults(caps, overrides).items():
        controls[key] = default
    return controls


__all__ = [
    "VisualizationCapabilities", "CAP_TO_KEY", "DISPLAY_KEYS", "display_controls_for",
    "display_defaults", "reset_display",
]
