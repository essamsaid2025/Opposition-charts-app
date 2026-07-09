"""Themes as data, not code. Each theme is one YAML file in assets/themes
(or the user themes dir). Adding a club/broadcast theme = adding a file.
The Theme object is consumed by CSS injection, PitchFactory and every visual."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from fap.core.exceptions import ConfigurationError

DEFAULT_CMAPS: tuple[str, ...] = ("Greens", "Blues", "Reds", "magma", "viridis")

REQUIRED_COLORS: tuple[str, ...] = (
    "bg", "panel", "pitch", "stripe", "text", "muted", "lines", "grid",
    "accent", "accent_2", "danger", "warning", "success", "grey", "bar",
)


@dataclass(frozen=True, slots=True)
class Theme:
    id: str
    name: str
    dark: bool
    colors: dict[str, str]
    fonts: dict[str, str] = field(default_factory=dict)
    heatmap_cmaps: tuple[str, ...] = DEFAULT_CMAPS

    def validate(self) -> None:
        missing = [c for c in REQUIRED_COLORS if c not in self.colors]
        if missing:
            raise ConfigurationError(f"Theme {self.id!r} missing colors: {missing}")


class ThemeManager:
    def __init__(self, *dirs: str | Path) -> None:
        self._themes: dict[str, Theme] = {}
        for directory in dirs:
            self._load_dir(Path(directory))

    def _load_dir(self, directory: Path) -> None:
        if not directory.exists():
            return
        for file in sorted(directory.glob("*.yaml")):
            data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
            theme = Theme(
                id=data.get("id", file.stem),
                name=data.get("name", file.stem),
                dark=bool(data.get("dark", False)),
                colors=dict(data.get("colors", {})),
                fonts=dict(data.get("fonts", {})),
                heatmap_cmaps=tuple(data.get("heatmap_cmaps", DEFAULT_CMAPS)),
            )
            theme.validate()
            self._themes[theme.id] = theme

    def get(self, theme_id: str) -> Theme:
        try:
            return self._themes[theme_id]
        except KeyError:
            raise ConfigurationError(f"Unknown theme {theme_id!r}") from None

    def ids(self) -> list[str]:
        return sorted(self._themes)

    def all(self) -> list[Theme]:
        return [self._themes[i] for i in self.ids()]
