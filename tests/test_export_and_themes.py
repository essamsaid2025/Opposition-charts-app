"""Export engine and theme engine tests."""
import matplotlib
matplotlib.use("Agg")
import zipfile
from io import BytesIO

import matplotlib.pyplot as plt
import pytest

from fap.themes import ThemeManager
from fap.visuals import ExportEngine, ImageEngine
from fap.visuals.pitch import PitchFactory

THEMES = ThemeManager("assets/themes")


def _fig():
    fig, _ = PitchFactory().build(THEMES.get("opta_light"))
    return fig


# ---------------------------------------------------------------- export engine
def test_export_png_svg_pdf_headers():
    engine = ExportEngine()
    fig = _fig()
    png = engine.export(fig, "Test Chart", fmt="png")
    svg = engine.export(fig, "Test Chart", fmt="svg")
    pdf = engine.export(fig, "Test Chart", fmt="pdf")
    assert png.data[:8] == b"\x89PNG\r\n\x1a\n" and png.mime == "image/png"
    assert b"<svg" in svg.data[:400] and svg.filename == "test_chart.svg"
    assert pdf.data[:5] == b"%PDF-" and pdf.mime == "application/pdf"
    plt.close(fig)


def test_export_dpi_presets_and_transparency():
    engine = ExportEngine()
    fig = _fig()
    small = engine.export(fig, "c", fmt="png", dpi="screen")
    print_dpi = engine.export(fig, "c", fmt="png", dpi=300)
    ultra = engine.export(fig, "c", fmt="png", dpi="ultra")
    assert len(small.data) < len(print_dpi.data) < len(ultra.data)
    transparent = engine.export(fig, "c", fmt="png", dpi="screen", transparent=True)
    assert transparent.data != small.data
    plt.close(fig)


def test_batch_export_zip():
    engine = ExportEngine()
    figs = [(_fig(), "Chart One"), (_fig(), "Chart Two")]
    result = engine.batch(figs, fmt="png", dpi="screen", archive_name="Match Report")
    assert result.mime == "application/zip" and result.filename == "match_report.zip"
    with zipfile.ZipFile(BytesIO(result.data)) as zf:
        assert set(zf.namelist()) == {"chart_one.png", "chart_two.png"}
    for fig, _ in figs:
        plt.close(fig)


def test_clipboard_png():
    fig = _fig()
    data = ExportEngine().clipboard_png(fig)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    plt.close(fig)


# ---------------------------------------------------------------- theme engine
def test_all_professional_themes_load():
    required = {"opta_dark", "opta_light", "statsbomb", "hudl", "athletic",
                "wyscout", "tv_broadcast", "presentation", "print", "dark",
                "light", "club_theme"}
    assert required <= set(THEMES.ids())
    for theme in THEMES.all():
        theme.validate()


def test_theme_tokens_flow_into_style():
    tv = THEMES.get("tv_broadcast")
    assert tv.tokens["uppercase_titles"] is True
    assert tv.tokens["title_size"] == 24


def test_custom_theme_creator(tmp_path):
    manager = ThemeManager("assets/themes", tmp_path)
    theme = manager.create_custom(
        "my_club", "My Club FC", base="club_theme",
        colors={"accent": "#00FF88"}, tokens={"title_size": 30}, dark=True)
    assert theme.colors["accent"] == "#00FF88"
    assert theme.colors["bg"] == "#0B1E3C"               # inherited from base
    assert (tmp_path / "my_club.yaml").exists()
    reloaded = ThemeManager("assets/themes", tmp_path)   # persists across restart
    assert reloaded.get("my_club").tokens["title_size"] == 30


# ---------------------------------------------------------------- image engine
def test_image_engine_load_and_place():
    from PIL import Image
    buf = BytesIO()
    Image.new("RGBA", (40, 40), (255, 0, 0, 128)).save(buf, format="PNG")
    img = ImageEngine.load(buf.getvalue())
    assert img.shape == (40, 40, 4)                      # alpha preserved
    fig = _fig()
    box = ImageEngine.place(fig.axes[0], img, anchor="bottom_left", zoom=0.2)
    assert box in fig.axes[0].artists
    plt.close(fig)
