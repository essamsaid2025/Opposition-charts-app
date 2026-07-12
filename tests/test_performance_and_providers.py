"""Phase-6 verification: performance on large datasets and compatibility of
the visualization library with every supported provider's canonical output."""
import json
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytest

from fap.cache import CacheManager
from fap.config.settings import CacheSettings
from fap.core.types import RenderContext
from fap.db.engine import Database
from fap.pipeline.importer import ImportService
from fap.pipeline.templates import TemplateRepository
from fap.themes import ThemeManager
from fap.visuals import Renderer, visual_registry
from fap.visuals.base import load_builtin_visuals
from tests.test_match_analysis_library import rich_dataset

load_builtin_visuals()
THEME = ThemeManager("assets/themes").get("opta_light")


# ---------------------------------------------------------------- performance
@pytest.fixture(scope="module")
def big_df():
    return rich_dataset(n=100_000, seed=5)


@pytest.mark.parametrize("viz_id,budget_s", [
    ("pass_map", 6.0),              # arrow maps sample to max_events
    ("defensive_heatmap", 5.0),     # density is vectorized
    ("pass_network", 6.0),
    ("expected_threat_map", 8.0),
    ("shot_map", 5.0),
])
def test_large_dataset_render_performance(big_df, viz_id, budget_s):
    viz = visual_registry.create(viz_id)
    ctx = RenderContext(df=big_df, theme=THEME, controls={"title": ""}, meta={})
    start = time.perf_counter()
    fig = Renderer().render(viz, ctx)
    elapsed = time.perf_counter() - start
    plt.close(fig)
    assert elapsed < budget_s, f"{viz_id} took {elapsed:.1f}s (budget {budget_s}s)"


def test_figure_cache_makes_reruns_instant(big_df):
    renderer = Renderer(cache=CacheManager(CacheSettings(backend="memory")))
    viz = visual_registry.create("pass_map")
    ctx = RenderContext(df=big_df, theme=THEME, controls={"title": "P"}, meta={})
    renderer.render_png(viz, ctx, dpi=100)
    start = time.perf_counter()
    renderer.render_png(viz, ctx, dpi=100)
    assert time.perf_counter() - start < 1.5      # cache hit dominated by hashing


# ---------------------------------------------------------------- providers
SB = json.dumps([{
    "type": {"name": "Pass"}, "team": {"name": "Barca"},
    "player": {"name": "Xavi"}, "minute": 10, "second": 3, "period": 1,
    "location": [60.0, 40.0],
    "pass": {"end_location": [95.0, 30.0], "length": 30.1,
             "recipient": {"name": "Iniesta"}},
}, {
    "type": {"name": "Shot"}, "team": {"name": "Barca"},
    "player": {"name": "Messi"}, "minute": 55, "second": 2, "period": 2,
    "location": [108.0, 36.0],
    "shot": {"end_location": [120.0, 40.0], "statsbomb_xg": 0.4,
             "outcome": {"name": "Goal"}},
}] * 40).encode()

WS = json.dumps({"events": [{
    "eventName": "Pass", "teamId": 1, "playerId": 9, "matchPeriod": "1H",
    "eventSec": 60.0 + i, "matchId": 7,
    "positions": [{"x": 40 + i % 30, "y": 30}, {"x": 60 + i % 30, "y": 50}],
    "tags": [{"id": 1801}]} for i in range(60)]}).encode()

OPTA = (b'<Games><Game id="g1"><Event id="1" type_id="1" period_id="1" min="4" '
        b'sec="1" team_id="t" player_id="p" outcome="1" x="40" y="50">'
        b'<Q qualifier_id="140" value="70"/><Q qualifier_id="141" value="45"/>'
        b'</Event><Event id="2" type_id="16" period_id="2" min="60" sec="0" '
        b'team_id="t" player_id="p2" outcome="1" x="90" y="50"/></Game></Games>')

PROVIDER_FILES = [
    ("statsbomb_events.json", SB),
    ("wyscout_match.json", WS),
    ("opta_f24.xml", OPTA),
    ("manual_tags.csv", b"event_type,x,y,end_x,end_y,player,team,minute\n"
                        b"pass,20,30,55,60,Ana,Lions,4\nshot,88,48,,,Ana,Lions,9\n"),
    ("metrica_events.csv",
     b"Team,Type,Subtype,Period,Start Frame,Start Time [s],End Time [s],From,To,"
     b"Start X,Start Y,End X,End Y\nHome,PASS,,1,1,3.0,4.5,P1,P2,0.4,0.3,0.7,0.5\n"),
    ("tracab_export.csv", b"event_type,x,y,end_x,end_y\npass,-1000,500,2000,-800\n"),
    ("second_spectrum_events.jsonl",
     b'{"event_type": "pass", "x": -20.0, "y": 5.0, "end_x": 10.0, "end_y": -8.0}'),
]


@pytest.mark.parametrize("filename,data", PROVIDER_FILES,
                         ids=[f[0].split(".")[0] for f in PROVIDER_FILES])
def test_library_compatible_with_every_provider(tmp_path, filename, data):
    """Any provider -> canonical model -> the same visualizations render."""
    importer = ImportService(CacheManager(CacheSettings(backend="memory")),
                             TemplateRepository(Database(tmp_path / "p.sqlite3")))
    result = importer.import_file(data, filename)
    assert result.frame["x"].dropna().between(0, 100).all()
    for viz_id in ("pass_map", "shot_map", "defensive_heatmap", "occupation_map"):
        viz = visual_registry.create(viz_id)
        fig = Renderer().render(viz, RenderContext(
            df=result.frame, theme=THEME, controls={"title": ""}, meta={}))
        plt.close(fig)
