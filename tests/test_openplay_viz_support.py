"""Data-driven Open Play chart availability (``fap.openplay.viz_support``).

Proves the picker offers only the charts a loaded frame can actually draw and hides
the rest, mirroring each renderer's data predicate — the "limited file shows fewer
options" behaviour. Pure: needs only pandas (no app import, no Streamlit).

Runnable directly (``pythonw test_openplay_viz_support.py`` writes PASS/FAIL to a
sibling ``.out`` file) since pytest is absent in the project interpreter.
"""
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

import pandas as pd  # noqa: E402

from fap.openplay.config import DEF_EVENTS  # noqa: E402
from fap.openplay.viz_support import (  # noqa: E402
    available_viz_names,
    has_end_coordinates,
    is_supported,
    present_event_types,
    unsupported_viz_names,
)

# The registered pitch/chart names the gate reasons about (order preserved).
ALL_NAMES = [
    "Overview Heatmap", "Heatmap Studio", "Pass Map", "Carry Map", "Cross Map",
    "Dribble Map", "Start / End Map", "Sequence Map", "Shot Map", "Zone Percentages",
    "Defensive Actions Map", "Event Distribution Bar", "Top Players Bar",
    "Pass Direction Bar", "Shot Result Bar", "Timeline Line Chart",
    "Match Trend Line Chart", "Statistical Table", "Match Summary Cards",
]
GENERIC = {
    "Overview Heatmap", "Heatmap Studio", "Sequence Map", "Zone Percentages",
    "Event Distribution Bar", "Top Players Bar", "Timeline Line Chart",
    "Match Trend Line Chart", "Statistical Table", "Match Summary Cards",
}


def _frame(event_types, *, end=True):
    n = len(event_types)
    data = {
        "event_type": list(event_types),
        "x": [10.0] * n, "y": [20.0] * n,
    }
    if end:
        data["x2"] = [30.0] * n
        data["y2"] = [40.0] * n
    return pd.DataFrame(data)


def test_present_event_types_normalizes():
    f = _frame([" Pass ", "SHOT", "", "shot", None])
    assert present_event_types(f) == frozenset({"pass", "shot"})
    assert present_event_types(None) == frozenset()
    assert present_event_types(pd.DataFrame({"x": [1]})) == frozenset()


def test_has_end_coordinates_both_vocabularies():
    assert has_end_coordinates(_frame(["pass"], end=True))
    assert not has_end_coordinates(_frame(["pass"], end=False))
    canonical = pd.DataFrame({"event_type": ["pass"], "end_x": [1.0], "end_y": [2.0]})
    assert has_end_coordinates(canonical)
    # present column but all-null -> no usable end coords
    null_end = pd.DataFrame({"event_type": ["pass"], "x2": [None], "y2": [None]})
    assert not has_end_coordinates(null_end)


def test_inferred_pass_only_file_hides_action_charts():
    """The user's 'After Cleaning.xlsx' case: import infers every row as ``pass``
    (start+end coords, no event type). Pass-based + generic charts stay; shot/carry/
    cross/dribble/defensive charts are hidden."""
    frame = _frame(["pass"] * 20, end=True)
    avail = available_viz_names(ALL_NAMES, frame)
    hidden = unsupported_viz_names(ALL_NAMES, frame)

    assert "Pass Map" in avail
    assert "Pass Direction Bar" in avail
    assert "Start / End Map" in avail          # end coords present
    assert GENERIC.issubset(set(avail))         # every generic chart offered
    for gone in ("Carry Map", "Cross Map", "Dribble Map", "Shot Map",
                 "Shot Result Bar", "Defensive Actions Map"):
        assert gone in hidden, gone
        assert gone not in avail, gone


def test_shot_file_offers_shot_charts_only():
    frame = _frame(["shot"] * 12, end=False)   # shots, no end coords
    avail = set(available_viz_names(ALL_NAMES, frame))
    assert {"Shot Map", "Shot Result Bar"}.issubset(avail)
    # no end coords -> arrow maps + start/end hidden even if their event existed
    for gone in ("Pass Map", "Carry Map", "Start / End Map", "Pass Direction Bar"):
        assert gone not in avail, gone


def test_defensive_events_gate_defensive_map():
    for ev in DEF_EVENTS:
        avail = set(available_viz_names(ALL_NAMES, _frame([ev] * 3, end=False)))
        assert "Defensive Actions Map" in avail, ev
    assert "Defensive Actions Map" not in set(
        available_viz_names(ALL_NAMES, _frame(["pass"] * 3)))


def test_rich_file_offers_everything():
    frame = _frame(["pass", "carry", "cross", "dribble", "shot", *DEF_EVENTS], end=True)
    avail = available_viz_names(ALL_NAMES, frame)
    assert avail == ALL_NAMES                    # nothing hidden, order preserved
    assert unsupported_viz_names(ALL_NAMES, frame) == []


def test_no_frame_or_empty_never_gates():
    assert available_viz_names(ALL_NAMES, None) == ALL_NAMES
    assert available_viz_names(ALL_NAMES, pd.DataFrame()) == ALL_NAMES
    # frame with rows but no event_type column -> unknown, show all
    no_et = pd.DataFrame({"x": [1.0], "y": [2.0]})
    assert available_viz_names(ALL_NAMES, no_et) == ALL_NAMES


def test_unknown_and_generic_names_always_supported():
    empty = frozenset()
    assert is_supported("Custom Dashboard", empty, False)      # not in table
    assert is_supported("Some Plugin Chart", empty, False)
    assert is_supported("Overview Heatmap", empty, False)
    # event-gated ones are not supported on an empty frame state
    assert not is_supported("Shot Map", empty, False)
    assert not is_supported("Pass Map", frozenset({"pass"}), False)  # needs end coords
    assert is_supported("Pass Map", frozenset({"pass"}), True)


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    lines, failed = [], 0
    for t in tests:
        try:
            t()
            lines.append(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            import traceback
            lines.append(f"FAIL {t.__name__}: {exc}\n{traceback.format_exc()}")
    lines.append(f"\n{len(tests) - failed}/{len(tests)} passed")
    out = "\n".join(lines)
    (pathlib.Path(__file__).with_suffix(".out")).write_text(out, encoding="utf-8")
    print(out)
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
