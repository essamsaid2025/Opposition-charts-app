"""Tagged-event export adapter (``fap.pipeline.tagged_events``).

Proves a free-text ``tag_name`` export is reshaped into canonical event columns —
each tag becomes its real ``event_type`` (+ ``outcome`` / ``shot_result``) instead of
every row collapsing to ``pass`` — while every other format is left untouched.

Runnable directly (pytest is absent in the project interpreter): writes PASS/FAIL to a
sibling ``.out`` file.
"""
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

import pandas as pd  # noqa: E402

from fap.pipeline.tagged_events import (  # noqa: E402
    event_type_for,
    looks_like_tagged_events,
    outcome_for,
    reshape,
    shot_result_for,
)


def _tag_frame(tags):
    n = len(tags)
    return pd.DataFrame({
        "Half": [1] * n, "tag_name": tags, "players": ["P"] * n, "team": ["T"] * n,
        "x": [10.0] * n, "y": [20.0] * n, "x2": [30.0] * n, "y2": [40.0] * n,
    })


def test_guard_fires_only_on_tag_exports():
    assert looks_like_tagged_events(_tag_frame(["Succ Short Pass"]))
    # already has event_type -> leave it alone
    df = _tag_frame(["Succ Short Pass"]); df["event_type"] = "pass"
    assert not looks_like_tagged_events(df)
    # no coordinates -> not an event export we reshape
    assert not looks_like_tagged_events(pd.DataFrame({"tag_name": ["x"]}))
    # no tag column -> untouched
    assert not looks_like_tagged_events(pd.DataFrame({"x": [1], "y": [2], "type": ["pass"]}))


def test_event_type_keyword_rules():
    cases = {
        "Succ Short Pass": "pass", "Fail Long Pass": "pass", "Key Pass": "pass",
        "Assist": "pass", "Chances Created From Corner": "pass",
        "Succ Pass From Throw In": "pass", "Succ Receive": "receive",
        "Carry": "carry", "Succ Dribble": "dribble", "Dribble Past": "dribble",
        "Dribble Tackle": "tackle",                 # tackle wins over dribble
        "Tackle Won": "tackle", "Intercept Won": "interception",
        "Intercept Clear": "interception",          # interception wins over clear
        "Clearances": "clearance", "Recover": "recovery", "Counter Press": "pressure",
        "Aerials Won": "duel", "Fail Cross": "cross", "Cross Saved": "cross",
        "Shot Off Target": "shot", "Goal": "shot", "Shot Blocked": "shot",
        "Ball Lost": "dispossessed", "Foul Comm": "foul", "Handball": "foul",
        "Offside": "offside",
    }
    for tag, expected in cases.items():
        assert event_type_for(tag) == expected, f"{tag} -> {event_type_for(tag)} != {expected}"


def test_unknown_tag_kept_not_dropped():
    assert event_type_for("Side Line") == "side line"
    assert event_type_for("Sub In") == "sub in"
    assert event_type_for("") == ""
    assert event_type_for(None) == ""


def test_outcome_from_wording():
    assert outcome_for("Succ Short Pass") == "successful"
    assert outcome_for("Tackle Won") == "successful"
    assert outcome_for("Dribble Past") == "successful"
    assert outcome_for("Fail Long Pass") == "unsuccessful"
    assert outcome_for("Aerials Lost") == "unsuccessful"
    assert outcome_for("Ball Lost") == "unsuccessful"
    assert outcome_for("Carry") == ""                # no outcome encoded
    assert outcome_for("Counter Press") == ""


def test_shot_result_only_for_shots():
    assert shot_result_for("Goal") == "Goal"
    assert shot_result_for("Shot Off Target") == "Off Target"
    assert shot_result_for("Shot On Target") == "On Target"
    assert shot_result_for("Shot Blocked") == "Blocked"
    assert shot_result_for("Succ Short Pass") == ""  # not a shot
    assert shot_result_for("Cross Saved") == ""       # a cross, not a shot


def test_reshape_adds_canonical_columns_and_preserves_original():
    df = _tag_frame(["Succ Short Pass", "Carry", "Goal", "Fail Cross", "Tackle Won"])
    out = reshape(df)
    assert list(out["event_type"]) == ["pass", "carry", "shot", "cross", "tackle"]
    assert list(out["outcome"]) == ["successful", "", "", "unsuccessful", "successful"]
    assert out.loc[2, "shot_result"] == "Goal"
    assert list(out["sub_event"]) == ["succ short pass", "carry", "goal", "fail cross", "tackle won"]
    assert "tag_name" in out.columns                 # original preserved
    assert out is not df                             # a copy


def test_non_tag_frame_passes_through_unchanged():
    df = pd.DataFrame({"x": [1.0], "y": [2.0], "type": ["pass"]})
    assert reshape(df) is df


def test_real_file_distribution_if_present():
    """When the user's real export is available, the collapse-to-pass bug is gone:
    many distinct actions, real shots with results."""
    path = pathlib.Path.home() / "Downloads" / "After Cleaning.xlsx"
    if not path.exists():
        return                                       # skip silently off the author's machine
    out = reshape(pd.read_excel(path))
    et = out["event_type"].value_counts()
    for kind in ("pass", "carry", "shot", "dribble", "tackle", "interception",
                 "recovery", "cross", "duel"):
        assert et.get(kind, 0) > 0, kind
    assert et.get("pass", 0) < len(out) * 0.5        # not everything is a pass any more
    shots = out[out["event_type"] == "shot"]
    assert (shots["shot_result"] == "Goal").sum() == 4


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
