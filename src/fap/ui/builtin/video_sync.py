"""Click-to-seek video sync — a tiny Streamlit *static* custom component.

Same lightweight, no-build pattern as ``fap.ui.studio.sortable`` and
``fap.ui.builtin.tactical_canvas``: the browser renders a seekable player and
only *reports intent* (the current playback time when the user marks kickoff);
all mutation/persistence stays in Python. If the component cannot initialise for
any reason, ``video_sync`` returns ``(False, None)`` and the Videos tab falls
back to today's plain ``st.video``/link rendering — playback always works.

Real programmatic seeking is only implemented for sources with a documented
public seek API: uploaded files (HTML5 ``video.currentTime``), YouTube (IFrame
Player API ``seekTo``) and Vimeo (Player SDK ``setCurrentTime``). Every other
external provider is left exactly as it is today (no seek UI is offered).

Everything above the component call is pure and unit-testable without a browser.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SEEKABLE_MODES = ("upload", "youtube", "vimeo")

_DIR = Path(__file__).resolve().parent / "frontend" / "video_sync"
_impl: Any = None

_YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})")
_VIMEO_RE = re.compile(r"vimeo\.com/(?:video/|channels/[^/]+/|groups/[^/]+/videos/)?(\d+)")


# ------------------------------------------------------------------ pure helpers
def event_video_time(offset_seconds: float, minute: Any, second: Any) -> float:
    """Video seek time for an event: ``offset + minute*60 + second``.

    ``offset_seconds`` is the video timestamp of kickoff. Missing/garbage
    minute/second count as 0; the result is clamped at 0 so a seek never goes
    negative. This is the single source of the calculation the UI performs."""
    def _num(v: Any) -> float:
        try:
            f = float(v)
            return f if f == f else 0.0            # NaN -> 0
        except (TypeError, ValueError):
            return 0.0
    return max(0.0, _num(offset_seconds) + _num(minute) * 60.0 + _num(second))


def event_video_time_2h(offset_1h: Any, offset_2h: Any, period: Any, minute: Any, second: Any,
                        *, half_start_minute: float = 45.0) -> float:
    """Period-aware seek for footage split between halves.

    First half (period <= 1) uses ``offset_1h`` exactly like ``event_video_time``. Second half
    (period >= 2) uses ``offset_2h`` PLUS the time elapsed since the second-half kickoff
    (``minute - half_start_minute``) — because a video's second half begins at its own timestamp
    (split footage, or a halftime gap), not 45 minutes after first-half kickoff. When ``offset_2h``
    is ``None`` (second half not calibrated) it falls back to the single continuous offset (today's
    behaviour). If ``period`` is missing/0 it is inferred from the minute (>= ``half_start_minute``
    => second half). Never negative."""
    def _num(v: Any) -> float:
        try:
            f = float(v)
            return f if f == f else 0.0
        except (TypeError, ValueError):
            return 0.0
    m = _num(minute)
    p = _num(period)
    is_second_half = (p >= 2) if p >= 1 else (m >= half_start_minute)
    if is_second_half and offset_2h is not None:
        elapsed = max(0.0, m - half_start_minute) * 60.0 + _num(second)
        return max(0.0, _num(offset_2h) + elapsed)
    return event_video_time(offset_1h, minute, second)


def youtube_id(url: str) -> str | None:
    m = _YOUTUBE_RE.search(str(url or ""))
    return m.group(1) if m else None


def vimeo_id(url: str) -> str | None:
    m = _VIMEO_RE.search(str(url or ""))
    return m.group(1) if m else None


def component_mode(video: Any) -> str | None:
    """The seek mode for a PlayerVideo, or ``None`` when the source cannot be
    seeked programmatically (Hudl, SkillCorner, plain URLs, …) — those keep
    today's rendering. ``video`` needs ``.kind`` and ``.url``."""
    if getattr(video, "kind", "") == "upload":
        return "upload"
    url = getattr(video, "url", "") or ""
    if youtube_id(url):
        return "youtube"
    if vimeo_id(url):
        return "vimeo"
    return None


def is_seekable(video: Any) -> bool:
    return component_mode(video) is not None


def parse_result(value: Any) -> dict[str, Any] | None:
    """Trust boundary: normalise the browser value into ``{"action":"mark",
    "time": float, "nonce": str}`` or ``None``. Never raises."""
    if not isinstance(value, dict) or value.get("action") != "mark":
        return None
    t = value.get("time")
    if not isinstance(t, (int, float)) or isinstance(t, bool) or t < 0:
        return None
    nonce = value.get("nonce")
    return {"action": "mark", "time": float(t),
            "nonce": str(nonce) if nonce is not None else ""}


# ------------------------------------------------------------------ component
def _component():
    global _impl
    if _impl is None:
        import streamlit.components.v1 as components
        _impl = components.declare_component("fap_video_sync", path=str(_DIR))
    return _impl


def video_sync(*, mode: str, src: str, mime: str = "", seek_to: float | None = None,
               seek_nonce: str = "", calibrate: bool = False, key: str,
               colors: dict[str, str] | None = None) -> tuple[bool, dict[str, Any] | None]:
    """Render the seekable player. Returns ``(rendered, intent)``.

    ``rendered`` is ``True`` when the iframe mounted (so the caller must NOT also
    draw the static fallback) and ``False`` when it could not initialise (caller
    degrades to plain ``st.video``/link). ``intent`` is the parsed ``mark`` action
    (or ``None``). ``src`` is a base64 ``data:`` URL for uploads, or the video id
    for YouTube/Vimeo. Never raises."""
    try:
        value = _component()(
            mode=mode, src=src, mime=mime,
            seek_to=(None if seek_to is None else float(seek_to)),
            seek_nonce=str(seek_nonce or ""), calibrate=bool(calibrate),
            colors=colors or {}, key=key, default=None)
    except Exception:
        return False, None
    return True, parse_result(value)
