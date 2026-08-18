"""Second-half video calibration — period-aware seek helper (split first/second-half footage).

First half uses the 1H offset; second half uses the 2H offset PLUS time elapsed since the
second-half kickoff (minute - 45). Falls back to the single continuous offset when 2H is not
calibrated, and infers the half from minute when the period column is absent.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from fap.ui.builtin.video_sync import event_video_time, event_video_time_2h


def test_first_half_uses_1h_offset():
    # period 1, 10:30 with 1H kickoff at 12s -> 12 + 630 = 642
    assert event_video_time_2h(12.0, 900.0, 1, 10, 30) == 12.0 + 10 * 60 + 30


def test_second_half_uses_2h_offset_and_elapsed_since_kickoff():
    # period 2, minute 50:15, 2H kickoff at video 1500s -> 1500 + (50-45)*60 + 15 = 1815
    assert event_video_time_2h(12.0, 1500.0, 2, 50, 15) == 1500.0 + 5 * 60 + 15


def test_second_half_falls_back_to_continuous_when_not_calibrated():
    # offset_2h is None -> behaves exactly like the single-offset helper (today's behaviour)
    assert event_video_time_2h(12.0, None, 2, 50, 15) == event_video_time(12.0, 50, 15)


def test_period_inferred_from_minute_when_missing():
    # no period column: minute >= 45 => treated as second half
    assert event_video_time_2h(12.0, 1500.0, None, 50, 0) == 1500.0 + 5 * 60
    assert event_video_time_2h(12.0, 1500.0, None, 20, 0) == event_video_time(12.0, 20, 0)


def test_never_negative_and_nan_safe():
    assert event_video_time_2h(None, None, None, None, None) == 0.0
    assert event_video_time_2h(0, 100.0, 2, 45, 0) == 100.0     # exactly at 2H kickoff -> elapsed 0


def test_service_2h_offset_roundtrip():
    # the document-based store round-trips and clears without a migration
    import matplotlib
    matplotlib.use("Agg")
    from fap.scouting.service import ScoutingService
    # exercise the pure doc logic via a light stub player (no DB): mimic get_player/_save_doc
    doc = {}

    class _P:
        document = doc
    svc = ScoutingService.__new__(ScoutingService)
    # get with nothing set
    svc.get_player = lambda pid: _P()
    assert svc.video_2h_offset("p", "v") is None
    # set path is exercised in the UI/DB tests; here we lock the read contract + JSON shape
    _P.document = {"video_2h_offsets": {"v": 1500.0}}
    assert svc.video_2h_offset("p", "v") == 1500.0
    assert svc.video_2h_offset("p", "other") is None
