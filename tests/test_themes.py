from pathlib import Path

from fap.themes import ThemeManager


def test_load_shipped_themes() -> None:
    manager = ThemeManager(Path("assets/themes"))
    assert "opta_light" in manager.ids()
    theme = manager.get("opta_light")
    assert theme.colors["accent"].startswith("#")
