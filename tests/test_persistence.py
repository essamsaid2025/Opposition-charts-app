from fap.core.events import EventBus
from fap.db.engine import Database
from fap.db.repositories import ProjectRepository, WorkspaceRepository
from fap.pipeline.filters import FilterSet
from fap.projects import ProjectService
from fap.workspaces import WorkspaceService


def test_workspace_and_project_roundtrip(tmp_path) -> None:
    db = Database(tmp_path / "test.sqlite3")
    events = EventBus()
    workspaces = WorkspaceService(WorkspaceRepository(db), events)
    projects = ProjectService(ProjectRepository(db), events)

    ws = workspaces.create("Opponent: Rivals FC")
    saved = projects.save(
        project_id=None, workspace_id=ws.id, name="Build-up vs Rivals",
        source={"provider": "generic_csv", "filename": "rivals.csv"},
        filters=FilterSet(event_types=("pass",), only_successful=True),
        visual_id="pass_map", controls={"arrow_width": 2.0}, theme_id="opta_light",
    )
    loaded = projects.load(saved.id)
    assert loaded is not None
    restored = projects.restore_filters(loaded)
    assert restored.event_types == ("pass",)
    assert restored.only_successful
    assert projects.list_for_workspace(ws.id)[0].name == "Build-up vs Rivals"
