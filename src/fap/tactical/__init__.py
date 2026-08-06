"""Tactical Board module (Phase 14) - an independent coaching workspace.

Production-ready, interaction-agnostic CORE (model, commands, undo/redo, render,
templates, persistence, export). The Streamlit page in ``fap.ui.builtin.tactical_board``
is the current interaction layer; a Phase 15 JavaScript drag-and-drop canvas replaces
only rendering+input, reusing this core unchanged.
"""
from fap.tactical.models import (
    Board, Frame, PitchSpec, TacticalObject, new_board, new_id,
    OBJECT_TYPES, PITCH_KINDS,
)
from fap.tactical.ops import History, apply_command, command_names, default_props
from fap.tactical.render import (
    board_svg, curvature_from_control_point, curve_control_point, DEFAULT_COLORS,
)
from fap.tactical.service import TacticalService
from fap.tactical.templates import builtin_template, builtin_names, FORMATION_NAMES, SCENARIO_NAMES

__all__ = [
    "Board", "Frame", "PitchSpec", "TacticalObject", "new_board", "new_id",
    "OBJECT_TYPES", "PITCH_KINDS", "History", "apply_command", "command_names",
    "default_props", "board_svg", "curve_control_point", "curvature_from_control_point",
    "DEFAULT_COLORS", "TacticalService",
    "builtin_template", "builtin_names", "FORMATION_NAMES", "SCENARIO_NAMES",
]
