"""Themes as data, not code. Each theme is one YAML file (shipped in
assets/themes or user-created in user_data/themes). A theme carries colors,
optional fonts, heatmap palettes and a ``tokens:`` section that overrides any
framework style token (see fap.visuals.tokens) - fully configurable, nothing
hardcoded.

ThemeManager.create_custom() is the Custom Theme Creator API: it derives a
new theme from any base, applies overrides, persists it as YAML and registers
it immediately."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    tokens: dict[str, Any] = field(default_factory=dict)
    heatmap_cmaps: tuple[str, ...] = DEFAULT_CMAPS

    def validate(self) -> None:
        missing = [c for c in REQUIRED_COLORS if c not in self.colors]
        if missing:
            raise ConfigurationError(f"Theme {self.id!r} missing colors: {missing}")


class ThemeManager:
    def __init__(self, *dirs: str | Path) -> None:
        self._themes: dict[str, Theme] = {}
        self._user_dir: Path | None = None
        for i, directory in enumerate(dirs):
            path = Path(directory)
            if i == len(dirs) - 1:
                self._user_dir = path          # last dir = writable user themes
            self._load_dir(path)

    def _load_dir(self, directory: Path) -> None:
        if not directory.exists():
            return
        for file in sorted(directory.glob("*.yaml")):
            self._themes[self._parse(file).id] = self._parse(file)

    @staticmethod
    def _parse(file: Path) -> Theme:
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        theme = Theme(
            id=data.get("id", file.stem),
            name=data.get("name", file.stem),
            dark=bool(data.get("dark", False)),
            colors=dict(data.get("colors", {})),
            fonts=dict(data.get("fonts", {})),
            tokens=dict(data.get("tokens", {})),
            heatmap_cmaps=tuple(data.get("heatmap_cmaps", DEFAULT_CMAPS)),
        )
        theme.validate()
        return theme

    # ------------------------------------------------------------ lookup
    def get(self, theme_id: str) -> Theme:
        try:
            return self._themes[theme_id]
        except KeyError:
            raise ConfigurationError(f"Unknown theme {theme_id!r}") from None

    def ids(self) -> list[str]:
        return sorted(self._themes)

    def all(self) -> list[Theme]:
        return [self._themes[i] for i in self.ids()]

    # ------------------------------------------------------------ custom creator
    def create_custom(self, theme_id: str, name: str, *, base: str = "opta_light",
                      colors: dict[str, str] | None = None,
                      tokens: dict[str, Any] | None = None,
                      dark: bool | None = None,
                      heatmap_cmaps: tuple[str, ...] | None = None) -> Theme:
        """Derive, persist and register a club/custom theme."""
        parent = self.get(base)
        merged_colors = dict(parent.colors); merged_colors.update(colors or {})
        merged_tokens = dict(parent.tokens); merged_tokens.update(tokens or {})
        theme = Theme(id=theme_id, name=name,
                      dark=parent.dark if dark is None else dark,
                      colors=merged_colors, fonts=dict(parent.fonts),
                      tokens=merged_tokens,
                      heatmap_cmaps=heatmap_cmaps or parent.heatmap_cmaps)
        theme.validate()
        if self._user_dir is not None:
            self._user_dir.mkdir(parents=True, exist_ok=True)
            (self._user_dir / f"{theme_id}.yaml").write_text(yaml.safe_dump({
                "id": theme.id, "name": theme.name, "dark": theme.dark,
                "colors": theme.colors, "fonts": theme.fonts, "tokens": theme.tokens,
                "heatmap_cmaps": list(theme.heatmap_cmaps),
            }, sort_keys=False), encoding="utf-8")
        self._themes[theme.id] = theme
        return theme
