"""Typography engine: consistent, scalable text styling for every layer.

Supports families, weight/italic, uppercase, letter spacing, alignment,
multi-line wrapping and automatic scaling with figure size.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Any

from fap.visuals.tokens import StyleTokens


@dataclass(frozen=True, slots=True)
class TextStyle:
    family: str = "DejaVu Sans"
    size: float = 11.0
    weight: str = "normal"           # normal | bold
    italic: bool = False
    uppercase: bool = False
    letter_spacing: float = 0.0      # inserted thin-space multiplier (0 = off)
    align: str = "center"            # left | center | right
    color: str = "#000000"
    wrap_width: int | None = None    # characters per line for multi-line

    # ---------------------------------------------------------------- API
    def format(self, text: str) -> str:
        out = text.upper() if self.uppercase else text
        if self.letter_spacing > 0:
            spacer = "\u2009" * max(1, round(self.letter_spacing))
            out = spacer.join(out)
        if self.wrap_width:
            out = "\n".join(textwrap.wrap(out, self.wrap_width) or [""])
        return out

    def kwargs(self, scale: float = 1.0) -> dict[str, Any]:
        return {
            "fontfamily": self.family,
            "fontsize": self.size * scale,
            "fontweight": self.weight,
            "fontstyle": "italic" if self.italic else "normal",
            "color": self.color,
            "ha": self.align,
        }

    @classmethod
    def title(cls, tokens: StyleTokens, color: str) -> "TextStyle":
        return cls(family=tokens.get("font_family"), size=tokens.get("title_size"),
                   weight=tokens.get("title_weight"), color=color,
                   uppercase=bool(tokens.get("uppercase_titles")),
                   letter_spacing=float(tokens.get("letter_spacing")))

    @classmethod
    def subtitle(cls, tokens: StyleTokens, color: str) -> "TextStyle":
        return cls(family=tokens.get("font_family"), size=tokens.get("subtitle_size"),
                   color=color)

    @classmethod
    def label(cls, tokens: StyleTokens, color: str) -> "TextStyle":
        return cls(family=tokens.get("font_family"), size=tokens.get("label_size"),
                   color=color)


def auto_scale(fig_width_inches: float, base_width: float = 11.8) -> float:
    """Scale factor so text stays proportional across figure/layout sizes."""
    return max(0.55, min(1.6, fig_width_inches / base_width))
