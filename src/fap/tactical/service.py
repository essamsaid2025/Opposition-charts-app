"""Tactical Board service (Phase 14) - persistence + export over EXISTING platform
services. No new persistence engine, no new export engine.

Boards, templates, sessions and animations are stored as WorkspaceManager *presets*
(``kind="tactical_*"``); favorites are a WorkspaceManager autosave scope. Export
produces the board's own SVG natively; PNG/PDF are derived from that SVG when a
converter is available (import-guarded), degrading to SVG otherwise. All of this is
UI-agnostic, so the Phase 15 JS canvas reuses it unchanged.
"""
from __future__ import annotations

from typing import Any

from fap.tactical.models import Board
from fap.tactical.render import board_svg

KIND_BOARD = "tactical_board"
KIND_TEMPLATE = "tactical_template"
KIND_SESSION = "tactical_session"
KIND_ANIMATION = "tactical_animation"
FAV_SCOPE = "tactical_favorites"


class TacticalService:
    """Thin façade. Reuses WorkspaceManager for storage; never a second engine."""

    def __init__(self, workspaces: Any = None) -> None:
        self._wm = workspaces

    # -- generic preset storage ---------------------------------------
    def _save(self, user, kind: str, board: Board, *, name: str,
              preset_id: str | None = None):
        if self._wm is None:
            return None
        return self._wm.save_preset(user, kind=kind, name=name or board.name,
                                    document=board.to_dict(), preset_id=preset_id)

    def _list(self, user, kind: str) -> list:
        if self._wm is None:
            return []
        try:
            return self._wm.list_presets(user, kind=kind)
        except Exception:
            return []

    def delete(self, user, preset_id: str) -> None:
        if self._wm is not None:
            try:
                self._wm.delete_preset(user, preset_id)
            except Exception:
                pass

    @staticmethod
    def board_of(preset) -> Board:
        return Board.from_dict(getattr(preset, "document", None) or {})

    # -- boards / templates / sessions / animations -------------------
    def save_board(self, user, board: Board, *, name: str = "", preset_id: str | None = None):
        return self._save(user, KIND_BOARD, board, name=name, preset_id=preset_id)

    def list_boards(self, user) -> list:
        return self._list(user, KIND_BOARD)

    def save_template(self, user, board: Board, *, name: str):
        return self._save(user, KIND_TEMPLATE, board, name=name)

    def list_templates(self, user) -> list:
        return self._list(user, KIND_TEMPLATE)

    def save_session(self, user, board: Board, *, name: str):
        return self._save(user, KIND_SESSION, board, name=name)

    def list_sessions(self, user) -> list:
        return self._list(user, KIND_SESSION)

    def save_animation(self, user, board: Board, *, name: str):
        return self._save(user, KIND_ANIMATION, board, name=name)

    def list_animations(self, user) -> list:
        return self._list(user, KIND_ANIMATION)

    # -- favorites (autosave scope, not presets) ----------------------
    def favorites(self, user) -> list[str]:
        if self._wm is None:
            return []
        try:
            return [str(x) for x in (self._wm.load_autosave(user, scope=FAV_SCOPE).get("ids") or [])]
        except Exception:
            return []

    def toggle_favorite(self, user, preset_id: str) -> None:
        if self._wm is None:
            return
        favs = self.favorites(user)
        favs.remove(preset_id) if preset_id in favs else favs.append(preset_id)
        try:
            self._wm.autosave(user, {"ids": favs}, scope=FAV_SCOPE)
        except Exception:
            pass

    # -- export (SVG native; PNG/PDF via matplotlib, cairosvg as an alt) ---
    def export_formats(self) -> list[str]:
        """SVG is always available. PNG/PDF are offered when a rasteriser is present —
        matplotlib (shipped) or cairosvg — so a coach can download a real image/PDF."""
        fmts = ["svg"]
        from fap.tactical import export_render
        if export_render.available():
            # gif rides the SAME matplotlib/Pillow path (one board_image per frame)
            fmts += ["png", "pdf", "gif"]
        else:
            try:
                import cairosvg  # noqa: F401
                fmts += ["png", "pdf"]
            except Exception:
                pass
        return fmts

    def export(self, board: Board, frame_index: int = 0, *, fmt: str = "svg",
               colors: dict[str, str] | None = None) -> tuple[bytes, str, str]:
        """Return (bytes, mime, filename). SVG is native; PNG/PDF are drawn from the same
        board model via matplotlib (falling back to cairosvg, then to SVG)."""
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in board.name).strip() or "board"
        if fmt == "gif":
            # gif is always an ALL-frames animation (frame_index is irrelevant here)
            try:
                from fap.tactical import export_render
                if export_render.available():
                    data = export_render.board_gif(board, colors=colors)
                    return data, "image/gif", f"{safe}.gif"
            except Exception:
                pass                                 # degrade to a single SVG below, like png/pdf
            svg = board_svg(board, frame_index, colors=colors)
            return svg.encode("utf-8"), "image/svg+xml", f"{safe}.svg"
        if fmt in ("png", "pdf"):
            # preferred: matplotlib draws the model straight to PNG/PDF (no native cairo)
            try:
                from fap.tactical import export_render
                if export_render.available():
                    data = export_render.board_image(board, frame_index, fmt=fmt, colors=colors)
                    mime = "image/png" if fmt == "png" else "application/pdf"
                    return data, mime, f"{safe}.{fmt}"
            except Exception:
                pass
            try:
                import cairosvg
                svg = board_svg(board, frame_index, colors=colors)
                data = (cairosvg.svg2png(bytestring=svg.encode("utf-8")) if fmt == "png"
                        else cairosvg.svg2pdf(bytestring=svg.encode("utf-8")))
                mime = "image/png" if fmt == "png" else "application/pdf"
                return data, mime, f"{safe}.{fmt}"
            except Exception:
                pass
        svg = board_svg(board, frame_index, colors=colors)
        return svg.encode("utf-8"), "image/svg+xml", f"{safe}.svg"

    # -- extension points (Phase 15+; declared, not implemented) ------
    def from_dataset_positions(self, frame_rows) -> Board | None:
        """FUTURE: build a board frame from dataset player positions. Stub only."""
        return None

    def overlays_for(self, board: Board) -> list[str]:
        """FUTURE: extra SVG overlays (Open Play viz / heatmaps). Stub returns none."""
        return []
