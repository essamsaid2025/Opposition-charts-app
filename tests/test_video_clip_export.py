"""Clip export — build a shot-list of clips (windows around selected actions) + YouTube deep links.

Pure/deterministic: each clip is [seek-pre, seek+post] around the event's period-aware video time
(so second-half clips use the 2H offset); CSV is a shot list; YouTube URLs get ?t=Ns deep links.
Actual video-file cutting (ffmpeg) is a separate concern and NOT done here.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from fap.ui.builtin import video_sync as VS


def test_youtube_seek_url():
    u = "https://www.youtube.com/live/HTRcWFHLvcA?si=-RTu1"
    assert VS.youtube_seek_url(u, 123.4) == "https://www.youtube.com/watch?v=HTRcWFHLvcA&t=123s"
    # non-youtube url is returned unchanged
    assert VS.youtube_seek_url("https://example.com/x.mp4", 30) == "https://example.com/x.mp4"


def test_build_clips_windows_and_periods():
    events = [
        {"minute": 10, "second": 0, "period": 1, "event_type": "Pass"},   # 1H
        {"minute": 50, "second": 0, "period": 2, "event_type": "Shot"},   # 2H
    ]
    clips = VS.build_clips(events, offset_1h=12.0, offset_2h=1500.0,
                           url="https://youtu.be/HTRcWFHLvcA", pre=4.0, post=6.0)
    # 1H: seek 12 + 600 = 612 ; window [608, 618]
    assert clips[0]["seek_seconds"] == 612.0
    assert clips[0]["clip_start_seconds"] == 608.0 and clips[0]["clip_end_seconds"] == 618.0
    # 2H: seek 1500 + (50-45)*60 = 1800 ; window [1796, 1806] ; youtube deep link at start-of-seek
    assert clips[1]["seek_seconds"] == 1800.0
    assert "t=1800s" in clips[1]["url"]


def test_clip_start_never_negative():
    clips = VS.build_clips([{"minute": 0, "second": 1, "period": 1, "event_type": "Kickoff"}],
                           offset_1h=0.0, pre=10.0, post=5.0)
    assert clips[0]["clip_start_seconds"] == 0.0        # clamped, never negative


def test_clips_to_csv_has_header_and_rows():
    csv = VS.clips_to_csv(VS.build_clips(
        [{"minute": 1, "second": 2, "period": 1, "event_type": "Pass"}], offset_1h=0.0))
    lines = [l for l in csv.splitlines() if l.strip()]
    assert lines[0].startswith("event_type,minute,second,seek_seconds")
    assert len(lines) == 2 and "Pass" in lines[1]
