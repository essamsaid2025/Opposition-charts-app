"""Typography tokens - one place for the font stack and type scale.

No component hard-codes a font; they read these tokens (via CSS variables). The
default stack is a professional system-font stack so no network fonts are
required; a club may point ``font_sans`` at a bundled face in assets/fonts.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

_SYSTEM_SANS = ('-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", '
                'Arial, "Noto Sans", sans-serif')
_SYSTEM_MONO = ('"SF Mono", "JetBrains Mono", "Cascadia Code", Consolas, '
                '"Liberation Mono", monospace')


@dataclass(frozen=True, slots=True)
class Typography:
    font_sans: str = _SYSTEM_SANS
    font_mono: str = _SYSTEM_MONO
    # type scale (rem)
    size_xs: str = "0.75rem"
    size_sm: str = "0.8125rem"
    size_base: str = "0.9375rem"
    size_lg: str = "1.0625rem"
    size_xl: str = "1.25rem"
    size_2xl: str = "1.5rem"
    size_3xl: str = "1.9rem"
    # weights
    weight_normal: int = 400
    weight_medium: int = 500
    weight_semibold: int = 600
    weight_bold: int = 750
    # line heights
    line_tight: str = "1.2"
    line_normal: str = "1.5"
    # letter spacing for headings
    tracking_tight: str = "-0.015em"

    def with_overrides(self, data: Mapping[str, Any]) -> "Typography":
        font = data.get("font") or data.get("font_sans")
        return replace(self, font_sans=str(font)) if font else self


DEFAULT_TYPOGRAPHY = Typography()
