"""Built-in Tactical Board templates (Phase 14) - formations + coaching scenarios.

Pure factories that return a ready ``Board`` (JSON-serializable via the model). The
UI lists these and lets the coach start from one; users can also save their own
templates through the WorkspaceManager (``service.save_template``) - these built-ins
need no persistence.
"""
from __future__ import annotations

from fap.tactical.models import Board, Frame, PitchSpec, TacticalObject, new_board, new_id


def _player(x: float, y: float, number: int, *, team: str = "home", role: str = "",
            gk: bool = False) -> TacticalObject:
    return TacticalObject(id=new_id(), type="player", x=x, y=y,
                          props={"number": number, "team": team, "role": role,
                                 "goalkeeper": gk, "captain": False, "name": ""})


def _ball(x: float, y: float) -> TacticalObject:
    return TacticalObject(id=new_id(), type="ball", x=x, y=y)


def _arrow(x, y, x2, y2, *, kind: str = "arrow") -> TacticalObject:
    return TacticalObject(id=new_id(), type=kind, x=x, y=y, props={"x2": x2, "y2": y2})


# formation -> list of (x, y, number, gk)
_FORMATIONS: dict[str, list[tuple[float, float, int, bool]]] = {
    "4-3-3": [(8, 50, 1, True), (24, 18, 3, False), (22, 38, 5, False), (22, 62, 4, False),
              (24, 82, 2, False), (45, 32, 8, False), (42, 50, 6, False), (45, 68, 10, False),
              (72, 20, 11, False), (78, 50, 9, False), (72, 80, 7, False)],
    "4-2-3-1": [(8, 50, 1, True), (24, 18, 3, False), (22, 40, 5, False), (22, 60, 4, False),
                (24, 82, 2, False), (40, 38, 6, False), (40, 62, 8, False), (60, 22, 11, False),
                (58, 50, 10, False), (60, 78, 7, False), (80, 50, 9, False)],
    "4-4-2": [(8, 50, 1, True), (24, 18, 3, False), (22, 40, 5, False), (22, 60, 4, False),
              (24, 82, 2, False), (48, 18, 11, False), (45, 40, 6, False), (45, 60, 8, False),
              (48, 82, 7, False), (74, 38, 9, False), (74, 62, 10, False)],
    "3-5-2": [(8, 50, 1, True), (22, 30, 5, False), (20, 50, 4, False), (22, 70, 6, False),
              (46, 12, 3, False), (48, 35, 8, False), (45, 50, 10, False), (48, 65, 7, False),
              (46, 88, 2, False), (76, 40, 9, False), (76, 60, 11, False)],
}


def formation_board(name: str) -> Board:
    b = new_board(f"{name} Formation")
    fr = b.frames[0]
    fr.name = name
    for x, y, num, gk in _FORMATIONS.get(name, _FORMATIONS["4-3-3"]):
        fr.objects.append(_player(x, y, num, team="home", gk=gk))
    return b


def _both_teams() -> list[TacticalObject]:
    home = [_player(x, y, n, team="home", gk=gk) for x, y, n, gk in _FORMATIONS["4-3-3"]]
    away = [_player(100 - x, y, n, team="away", gk=gk) for x, y, n, gk in _FORMATIONS["4-4-2"]]
    return home + away


def _scenario_setpiece() -> Board:
    b = new_board("Set Piece - Attacking Corner", pitch_kind="full")
    b.pitch.area = "att_third"                       # frame the attacking third + box (no wasted space)
    fr = b.frames[0]; fr.name = "Corner"
    fr.objects.append(_ball(96, 4))
    box = [(80, 30, 9), (82, 45, 10), (84, 55, 4), (80, 62, 5), (88, 40, 11)]
    for x, y, n in box:
        fr.objects.append(_player(x, y, n, team="home"))
    for x, y, n in [(78, 32, 3), (81, 46, 6), (83, 56, 2), (90, 50, 1)]:
        fr.objects.append(_player(x, y, n, team="away", gk=(n == 1)))
    fr.objects.append(_arrow(96, 5, 84, 48, kind="curved_arrow"))
    return b


def _scenario(name: str, arrows: list[tuple]) -> Board:
    b = new_board(name)
    fr = b.frames[0]; fr.name = name.split(" - ")[-1] if " - " in name else name
    fr.objects.extend(_both_teams())
    fr.objects.append(_ball(50, 50))
    for a in arrows:
        fr.objects.append(_arrow(*a))
    return b


def scenario_board(key: str) -> Board:
    if key == "Set Pieces":
        return _scenario_setpiece()
    if key == "Pressing":
        return _scenario("Pressing - High Block",
                         [(45, 32, 30, 40), (42, 50, 30, 50), (45, 68, 30, 60)])
    if key == "Build-up":
        return _scenario("Build-up - From the Back",
                         [(8, 50, 22, 38), (22, 38, 42, 50), (22, 62, 45, 68)])
    if key == "Transitions":
        return _scenario("Transition - Counter Attack",
                         [(45, 50, 72, 30), (45, 50, 78, 50), (45, 50, 72, 70)])
    return new_board(key)


FORMATION_NAMES: tuple[str, ...] = ("4-3-3", "4-2-3-1", "4-4-2", "3-5-2")
SCENARIO_NAMES: tuple[str, ...] = ("Set Pieces", "Pressing", "Build-up", "Transitions")


def builtin_template(name: str) -> Board:
    """One entry point the UI uses for any built-in template name."""
    if name in FORMATION_NAMES:
        return formation_board(name)
    return scenario_board(name)


def builtin_names() -> list[str]:
    return list(FORMATION_NAMES) + list(SCENARIO_NAMES)
