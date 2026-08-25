"""Platform display-configuration + Data & Methodology foundation.

Presentation-only display controls (capability-gated) and an honest, dynamic
provenance note. These tests pin the transparency/independence guarantees the
upgrade is built on — before any renderer wiring:

* capabilities gate which controls appear (no Show xG on a passing map);
* display defaults reproduce current output (backward compatible);
* reset restores ONLY display, never analytical state;
* the methodology note reflects the ACTUAL config and updates with filters.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from fap.openplay.viz_descriptors import (
    describe, normalize_openplay_selections, openplay_note, scope_from_selections,
)
from fap.pipeline.filters import FilterSet
from fap.visuals.display import (
    VisualizationCapabilities, display_controls_for, display_defaults, reset_display,
)
from fap.visuals.methodology import build_note, coordinate_note, filter_labels


# ================================================================ capabilities gate
def test_capabilities_expose_only_supported_controls():
    shot = VisualizationCapabilities(values=True, legend=True, xg=True, xg_values=True,
                                     outcome=True, player_names=True)
    keys = set(shot.control_keys())
    assert {"show_xg", "show_xg_values", "show_outcome", "show_player_names"} <= keys
    labels = {c.key for c in display_controls_for(shot)}
    assert labels == keys                                # strict: only supported

    passing = VisualizationCapabilities(legend=True, outcome=True, player_names=True)
    pkeys = {c.key for c in display_controls_for(passing)}
    assert "show_xg" not in pkeys and "show_xg_values" not in pkeys   # no xG on a pass map
    assert {"legend", "show_outcome", "show_player_names"} <= pkeys


def test_display_controls_are_checkboxes_with_defaults():
    caps = VisualizationCapabilities(xg=True, xg_values=True, legend=True)
    by_key = {c.key: c for c in display_controls_for(caps)}
    assert by_key["show_xg"].kind == "checkbox" and by_key["show_xg"].default is True
    assert by_key["show_xg_values"].default is False   # xG numbers hidden by default
    assert by_key["legend"].default is True


# ================================================================ defaults + reset
def test_defaults_reproduce_current_output():
    d = display_defaults()
    assert d["legend"] is True
    assert d["show_labels"] is False and d["show_player_names"] is False
    assert d["show_zone_overlay"] is True and d["show_grid"] is False
    assert d["show_xg"] is True and d["show_xg_values"] is False
    assert d["show_outcome"] is True and d["show_percentages"] is True


def test_reset_touches_only_display_state():
    caps = VisualizationCapabilities(legend=True, xg=True, xg_values=True)
    controls = {
        "legend": False, "show_xg": False, "show_xg_values": True,   # display (reset)
        "team": "Barcelona", "player": "Messi", "marker_size": 200,   # NOT display
        "title": "My chart",
    }
    reset_display(controls, caps)
    assert controls["legend"] is True and controls["show_xg"] is True
    assert controls["show_xg_values"] is False
    # analytical / non-display state untouched
    assert controls["team"] == "Barcelona" and controls["player"] == "Messi"
    assert controls["marker_size"] == 200 and controls["title"] == "My chart"


# ================================================================ methodology note
def _fs() -> FilterSet:
    return FilterSet(team="FC Masar", event_types=("pass",), outcomes=("successful",),
                     minute_range=(0.0, 45.0))


def test_note_is_honest_and_dynamic():
    fields = ["event_type", "x", "y", "end_x", "end_y", "outcome"]
    empty = build_note(dataset="events", fields=fields, filters=FilterSet(),
                       metric="Progressive Passes", pitch_based=True,
                       length=105, width=68, spec_label="UEFA", scope="Team")
    rows = dict(empty.rows())
    assert rows["Dataset"] == "events"
    assert rows["Fields"] == "event_type, x, y, end_x, end_y, outcome"
    assert rows["Filters"] == "None"
    assert rows["Metric"] == "Progressive Passes"
    assert "105 × 68" in rows["Coordinates"] and "UEFA" in rows["Coordinates"]
    assert rows["Scope"] == "Team"
    assert "excluded from spatial rendering" in rows["Missing data"]

    # change a filter -> the note changes
    active = build_note(dataset="events", fields=fields, filters=_fs(),
                        metric="Progressive Passes", pitch_based=True)
    chips = dict(active.rows())["Filters"]
    assert "Team: FC Masar" in chips and "Event: pass" in chips
    assert "Only" not in chips and "Minutes: 0–45" in chips


def test_filter_labels_ignore_defaults():
    assert filter_labels(FilterSet()) == []
    assert filter_labels(None) == []
    labels = filter_labels(FilterSet(only_successful=True, players=("Messi",)))
    assert "Only successful" in labels and "Player: Messi" in labels


def test_coordinate_note_non_spatial():
    assert coordinate_note(False) == "n/a (non-spatial chart)"
    assert "0–100" in coordinate_note(True)


# ================================================================ open play descriptors
def test_descriptor_fields_and_caps_per_family():
    shot = describe("Shot Map", "Shooting", uses_pitch=True)
    assert "xg" in shot.fields and "outcome" in shot.fields
    passmap = describe("Progressive Pass Map", "Passing", uses_pitch=True)
    assert "end_x" in passmap.fields and "outcome" in passmap.fields
    assert "xg" not in passmap.fields                       # no xG on a pass map
    assert passmap.capabilities.player_names is True
    density = describe("Pressure Heatmap", "Defensive", uses_pitch=True)
    assert density.capabilities.event_counts is True        # cell counts honourable
    chart = describe("Pass Accuracy Bar", "Team", uses_pitch=False)
    assert chart.pitch_based is False
    ckeys = {c.key for c in display_controls_for(chart.capabilities)}
    assert ckeys == {"legend"}                              # engine only honours legend here


def test_openplay_note_uses_selections_and_spec():
    desc = describe("Shot Map", "Shooting", uses_pitch=True)
    note = openplay_note(desc, dataset="events",
                         filters={"team": "FC Masar", "players": ["Messi"]},
                         scope=scope_from_selections({"players": ["Messi"]}),
                         length=105, width=68, spec_label="UEFA")
    rows = dict(note.rows())
    assert rows["Scope"] == "Player · Messi"
    assert "Team: FC Masar" in rows["Filters"] and "Player: Messi" in rows["Filters"]
    assert "xg" in rows["Fields"]


def test_scope_from_selections_priority():
    assert scope_from_selections({"players": ["A", "B"]}) == "Players · 2 selected"
    assert scope_from_selections({"match": "M1"}) == "Match · M1"
    assert scope_from_selections({"team": "T"}) == "Team · T"
    assert scope_from_selections({}) == "All events"


def test_display_panel_ui_renders_in_bare_mode():
    """The shared UI helpers must render without a Streamlit runtime (bare mode),
    like every other page test — proving no runtime dependency leaks in."""
    import streamlit as st
    st.session_state.clear()
    from fap.ui.components.display_panel import (
        render_display_controls, render_methodology_note,
    )
    caps = describe("Shot Map", "Shooting", uses_pitch=True).capabilities
    out = render_display_controls(caps, {"legend": True}, key="t_disp")
    assert "legend" in out                                   # returns the display dict
    note = openplay_note(describe("Shot Map", "Shooting"), dataset="events")
    render_methodology_note(note, key="t_note")              # must not raise


def test_normalize_openplay_selections_maps_keys():
    # Open Play uses match/only_success; the note summariser expects match_id/only_successful
    norm = normalize_openplay_selections(
        {"match": "M1", "only_success": True, "event_types": ["pass"]})
    assert norm["match_id"] == "M1" and norm["only_successful"] is True
    chips = build_note(dataset="events", filters=norm, pitch_based=True).filters
    assert any("Match: M1" in c for c in chips) and "Only successful" in chips
