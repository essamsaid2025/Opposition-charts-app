"""Typography tokens - one place for the font stack and type scale.

No component hard-codes a font; they read these tokens (via CSS variables). The
default stack is a professional system-font stack so no network fonts are
required; a club may point ``font_sans`` at a bundled face in assets/fonts.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

# Modern professional UI face (StatsBomb/Hudl aesthetic). "Inter" is loaded via
# a Google Fonts @import in the stylesheet; the system stack is the fallback so
# the app still renders cleanly offline or if the font host is blocked.
_SYSTEM_SANS = ('"Inter", "Inter var", -apple-system, BlinkMacSystemFont, "Segoe UI", '
                'Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif')
_SYSTEM_MONO = ('"SF Mono", "JetBrains Mono", "Cascadia Code", Consolas, '
                '"Liberation Mono", monospace')


@dataclass(frozen=True, slots=True)
class Typography:
    font_sans: str = _SYSTEM_SANS
    font_mono: str = _SYSTEM_MONO
    # type scale (rem)
    size_2xs: str = "0.6875rem"
    size_xs: str = "0.75rem"
    size_sm: str = "0.8125rem"
    size_base: str = "0.9375rem"
    size_lg: str = "1.0625rem"
    size_xl: str = "1.25rem"
    size_2xl: str = "1.5rem"
    size_3xl: str = "1.9rem"
    size_4xl: str = "2.4rem"
    # weights
    weight_normal: int = 400
    weight_medium: int = 500
    weight_semibold: int = 600
    weight_bold: int = 700
    weight_extrabold: int = 800
    weight_black: int = 850
    # line heights
    line_tight: str = "1.2"
    line_snug: str = "1.35"
    line_normal: str = "1.5"
    # letter spacing
    tracking_tighter: str = "-0.03em"
    tracking_tight: str = "-0.015em"
    tracking_wide: str = "0.02em"
    tracking_wider: str = "0.08em"
    # numeric feature set for stat/metric surfaces (aligned tabular figures)
    feature_tabular: str = '"tnum" 1, "cv01" 1, "ss01" 1'

    def with_overrides(self, data: Mapping[str, Any]) -> "Typography":
        font = data.get("font") or data.get("font_sans")
        return replace(self, font_sans=str(font)) if font else self


DEFAULT_TYPOGRAPHY = Typography()
