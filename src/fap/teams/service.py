"""Team service — create/list/edit teams and manage rosters. Reuses the shared relational
engine, ImageStorage (crest) and audit; adds no duplicate persistence. Permission gating is
done in the UI (role-based, like the other pages); the service records created_by/audit."""
from __future__ import annotations

import uuid
from typing import Any

from fap.db.engine import Database
from fap.teams.models import Team, TeamMatch, TeamMedia, TeamMember, VENUES
from fap.teams.repository import TeamRepository


class TeamService:
    def __init__(self, db: Database, *, images: Any = None, files: Any = None, audit: Any = None,
                 workspaces: Any = None) -> None:
        self.repo = TeamRepository(db)
        self._images = images
        self._files = files            # FileStorage for uploaded videos/documents (T4)
        self._audit = audit
        self._wm = workspaces          # for the shared operational-id counter (never-reused ids)

    @staticmethod
    def _uid() -> str:
        return uuid.uuid4().hex

    def _assign_operational_id(self, team_kind: str) -> str:
        """A unique, human-readable operational id for a roster player, by squad: academy team ->
        ACD, club team -> CLB. Draws from the SAME never-reused per-prefix counter the scouting
        registry uses, so ids are globally unique across scouting/first-team/teams. (An SCT- id
        only appears when an existing scouting player is linked with their id supplied.)"""
        from fap.scouting import identity
        pt = "academy" if team_kind == "academy" else "first_team"
        prefix = identity.TYPE_PREFIX.get(pt, "CLB")
        seq = self._wm.next_counter(f"scouting_op_{prefix}") if self._wm is not None else 0
        return identity.format_operational_id(pt, seq)

    def _record(self, user: Any, action: str, **detail: Any) -> None:
        if self._audit is not None:
            try:
                self._audit.record(user, action, detail=detail)
            except Exception:
                pass

    # ---- teams ----
    def create_team(self, user: Any, name: str, *, kind: str = "club", age_group: str = "",
                    competition: str = "", season: str = "", info: str = "") -> Team:
        name = str(name or "").strip()
        if not name:
            raise ValueError("Team name is required.")
        t = Team(id=self._uid(), name=name, kind=(kind if kind in ("club", "academy") else "club"),
                 age_group=str(age_group or "").strip(), competition=str(competition or "").strip(),
                 season=str(season or "").strip(), info=str(info or "").strip(),
                 created_by=getattr(user, "email", "") or "")
        self.repo.add(t)
        self._record(user, "teams.create", team_id=t.id, name=name)
        return t

    def list_teams(self) -> list[Team]:
        return self.repo.list()

    def get_team(self, team_id: str) -> Team | None:
        return self.repo.get(team_id)

    def update_team(self, user: Any, team_id: str, **fields: Any) -> Team | None:
        self.repo.update(team_id, **fields)
        self._record(user, "teams.update", team_id=team_id)
        return self.repo.get(team_id)

    def delete_team(self, user: Any, team_id: str) -> None:
        t = self.repo.get(team_id)
        if t is not None and t.crest_image_id and self._images is not None:
            try:
                self._images.delete(t.crest_image_id)
            except Exception:
                pass
        if self._images is not None:
            for member in self.repo.list_members(team_id):
                if member.profile_image_id:
                    try:
                        self._images.delete(member.profile_image_id)
                    except Exception:
                        pass
        self.repo.delete(team_id)
        self._record(user, "teams.delete", team_id=team_id)

    def set_crest(self, user: Any, team_id: str, data: bytes, mime: str) -> Team | None:
        """Store a club/team crest, reusing ImageStorage (no new media store)."""
        if self._images is None:
            raise ValueError("Image storage is not configured.")
        t = self.repo.get(team_id)
        if t is None:
            return None
        if t.crest_image_id:
            try:
                self._images.delete(t.crest_image_id)
            except Exception:
                pass
        image_id = self._uid()
        self._images.save(image_id, data, mime=mime)
        self.repo.update(team_id, crest_image_id=image_id)
        self._record(user, "teams.crest", team_id=team_id)
        return self.repo.get(team_id)

    def crest_bytes(self, team_id: str) -> bytes | None:
        t = self.repo.get(team_id)
        if t is None or not t.crest_image_id or self._images is None:
            return None
        try:
            return self._images.load(t.crest_image_id)
        except Exception:
            return None

    # ---- linked datasets (opposition data files) --------------------------------
    # A team can link one or more Data Hub datasets (e.g. an opposition team's event
    # data file). Links live in teams.document['datasets'] and are read BY dataset_id
    # (active-INDEPENDENT): the data keeps showing regardless of which dataset is
    # currently active in the Data Hub — mirroring the scouting/first-team pattern.
    @staticmethod
    def _now() -> str:
        import datetime as _dt
        return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()

    @staticmethod
    def _links(t: Team) -> list[dict[str, Any]]:
        doc = getattr(t, "document", None) or {}
        links = doc.get("datasets")
        return [dict(x) for x in links] if isinstance(links, list) else []

    def available_datasets(self, workspace_id: str | None = None) -> list[Any]:
        """Datasets in the workspace the user can link (Data Hub datasets)."""
        if self._wm is None:
            return []
        try:
            return self._wm.list_datasets(workspace_id=workspace_id)
        except Exception:
            return []

    def link_dataset(self, user: Any, team_id: str, dataset_id: str, *,
                     match_id: str = "") -> Team | None:
        """Link a Data Hub dataset to a team by id. Idempotent (re-linking refreshes
        the cached name/rows). Never changes the active dataset or the dataset itself."""
        dataset_id = str(dataset_id or "").strip()
        if not dataset_id:
            raise ValueError("Choose a dataset to link.")
        t = self.repo.get(team_id)
        if t is None:
            return None
        if self._wm is None:
            raise ValueError("Data Hub is not available in this session.")
        ds = self._wm.get_dataset(dataset_id)
        if ds is None:
            raise ValueError("That dataset no longer exists in the Data Hub.")
        links = [x for x in self._links(t) if x.get("dataset_id") != dataset_id]
        links.append({"dataset_id": dataset_id, "dataset_name": ds.name,
                      "match_id": str(match_id or "").strip(), "rows": int(getattr(ds, "rows", 0) or 0),
                      "linked_by": getattr(user, "email", "") or "", "linked_at": self._now()})
        doc = dict(t.document or {})
        doc["datasets"] = links
        self.repo.update(team_id, document=doc)
        self._record(user, "teams.dataset.link", team_id=team_id, dataset_id=dataset_id)
        return self.repo.get(team_id)

    def unlink_dataset(self, user: Any, team_id: str, dataset_id: str) -> Team | None:
        t = self.repo.get(team_id)
        if t is None:
            return None
        links = [x for x in self._links(t) if x.get("dataset_id") != str(dataset_id)]
        doc = dict(t.document or {})
        doc["datasets"] = links
        self.repo.update(team_id, document=doc)
        self._record(user, "teams.dataset.unlink", team_id=team_id, dataset_id=dataset_id)
        return self.repo.get(team_id)

    def list_linked_datasets(self, team_id: str, *, user: Any = None) -> list[dict[str, Any]]:
        """The team's linked datasets, each enriched (read by id, active-independent)
        with live availability, current row count, and whether it is the active one.
        ``user`` is used only to flag which link (if any) is the active dataset."""
        t = self.repo.get(team_id)
        if t is None:
            return []
        active_id = None
        if self._wm is not None and user is not None:
            try:
                active_id = self._wm.active_dataset_id(user)
            except Exception:
                active_id = None
        out: list[dict[str, Any]] = []
        for link in self._links(t):
            ds_id = link.get("dataset_id", "")
            ds = self._wm.get_dataset(ds_id) if self._wm is not None else None
            out.append({**link, "available": ds is not None,
                        "current_name": (ds.name if ds is not None else link.get("dataset_name", "")),
                        "current_rows": int(getattr(ds, "rows", 0) or 0) if ds is not None else link.get("rows", 0),
                        "is_active": bool(active_id) and ds_id == active_id})
        return out

    def team_dataset_frame(self, team_id: str, dataset_id: str):
        """The full event frame of a team's linked dataset, read BY id (active-independent).
        None when the link is missing or the dataset is gone/empty."""
        t = self.repo.get(team_id)
        if t is None or self._wm is None:
            return None
        if not any(x.get("dataset_id") == str(dataset_id) for x in self._links(t)):
            return None
        try:
            frame = self._wm.dataset_frame(dataset_id)
        except Exception:
            return None
        return frame if frame is not None and not getattr(frame, "empty", True) else None

    # ---- roster ----
    def add_member(self, user: Any, team_id: str, *, player_name: str, operational_id: str = "",
                   player_id: str = "", source: str = "scouting", shirt_number: str = "",
                   role: str = "", **profile: Any) -> TeamMember:
        name = str(player_name or "").strip()
        oid = str(operational_id or "").strip()
        if not name and not oid:
            raise ValueError("A player name is required.")
        src = source if source in ("scouting", "first_team") else "scouting"
        if not oid:                    # no id supplied -> auto-assign a unique one for this squad
            t = self.repo.get(team_id)
            oid = self._assign_operational_id(t.kind if t else "club")
        m = TeamMember(id=self._uid(), team_id=team_id, player_id=str(player_id or ""),
                       operational_id=oid, player_name=name, source=src,
                       shirt_number=str(shirt_number or "").strip(), role=str(role or "").strip(),
                       **self._member_fields(profile))
        self.repo.add_member(m)
        self._record(user, "teams.member.add", team_id=team_id, name=name)
        return m

    @staticmethod
    def _member_fields(fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {"secondary_role", "date_of_birth", "nationality", "preferred_foot",
                   "height_cm", "weight_kg", "joined_date", "contract_end", "availability",
                   "phone", "email", "emergency_contact", "agent", "notes", "profile_image_id"}
        out: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in {"height_cm", "weight_kg"}:
                try:
                    out[key] = int(value) if value not in (None, "") else None
                except (TypeError, ValueError):
                    out[key] = None
            else:
                out[key] = str(value or "").strip()
        return out

    def update_member(self, user: Any, member_id: str, **fields: Any) -> TeamMember | None:
        core = {k: fields[k] for k in ("player_name", "operational_id", "shirt_number", "role") if k in fields}
        core.update(self._member_fields(fields))
        self.repo.update_member(member_id, **core)
        self._record(user, "teams.member.update", member_id=member_id)
        return self.repo.get_member(member_id)

    def set_member_photo(self, user: Any, member_id: str, data: bytes, mime: str) -> TeamMember | None:
        """Store a club-player image using the shared ImageStorage, replacing any old photo."""
        if self._images is None:
            raise ValueError("Image storage is not configured.")
        member = self.repo.get_member(member_id)
        if member is None:
            return None
        if member.profile_image_id:
            try:
                self._images.delete(member.profile_image_id)
            except Exception:
                pass
        image_id = self._uid()
        self._images.save(image_id, data, mime=mime)
        self.repo.update_member(member_id, profile_image_id=image_id)
        self._record(user, "teams.member.photo", member_id=member_id)
        return self.repo.get_member(member_id)

    def member_photo_bytes(self, member_id: str) -> bytes | None:
        member = self.repo.get_member(member_id)
        if member is None or not member.profile_image_id or self._images is None:
            return None
        try:
            return self._images.load(member.profile_image_id)
        except Exception:
            return None

    def list_members(self, team_id: str) -> list[TeamMember]:
        return self.repo.list_members(team_id)

    def remove_member(self, user: Any, member_id: str) -> None:
        member = self.repo.get_member(member_id)
        if member is not None and member.profile_image_id and self._images is not None:
            try:
                self._images.delete(member.profile_image_id)
            except Exception:
                pass
        self.repo.remove_member(member_id)
        self._record(user, "teams.member.remove", member_id=member_id)

    # ---- matches (T3) ----
    @staticmethod
    def _int_or_none(v: Any):
        try:
            return None if v is None or str(v).strip() == "" else int(v)
        except (TypeError, ValueError):
            return None

    def create_match(self, user: Any, team_id: str, *, opponent: str, match_date: str = "",
                     competition: str = "", venue: str = "home", our_score: Any = None,
                     opp_score: Any = None, formation: str = "", notes: str = "",
                     dataset_id: str = "", match_id: str = "") -> TeamMatch:
        opp = str(opponent or "").strip()
        if not opp:
            raise ValueError("An opponent is required.")
        m = TeamMatch(id=self._uid(), team_id=team_id, opponent=opp,
                      match_date=str(match_date or "").strip(),
                      competition=str(competition or "").strip(),
                      venue=(venue if venue in VENUES else "home"),
                      our_score=self._int_or_none(our_score), opp_score=self._int_or_none(opp_score),
                      formation=str(formation or "").strip(), notes=str(notes or "").strip(),
                      dataset_id=str(dataset_id or ""), match_id=str(match_id or "").strip(),
                      created_by=getattr(user, "email", "") or "")
        self.repo.add_match(m)
        self._record(user, "teams.match.create", team_id=team_id, opponent=opp)
        return m

    def list_matches(self, team_id: str) -> list[TeamMatch]:
        return self.repo.list_matches(team_id)

    def get_match(self, match_row_id: str) -> TeamMatch | None:
        return self.repo.get_match(match_row_id)

    def update_match(self, user: Any, match_row_id: str, **fields: Any) -> TeamMatch | None:
        for k in ("our_score", "opp_score"):
            if k in fields:
                fields[k] = self._int_or_none(fields[k])
        self.repo.update_match(match_row_id, **fields)
        self._record(user, "teams.match.update", match_id=match_row_id)
        return self.repo.get_match(match_row_id)

    def delete_match(self, user: Any, match_row_id: str) -> None:
        self.repo.delete_match(match_row_id)
        self._record(user, "teams.match.delete", match_id=match_row_id)

    # ---- media: notes / videos / clips / charts (T4) ----
    def add_note(self, user: Any, team_id: str, *, title: str = "", body: str = "",
                 match_id: str = "", member_id: str = "") -> TeamMedia:
        title, body = str(title or "").strip(), str(body or "").strip()
        if not title and not body:
            raise ValueError("A note title or body is required.")
        m = TeamMedia(id=self._uid(), team_id=team_id, match_id=str(match_id or ""), kind="note",
                      member_id=str(member_id or ""), title=title, body=body,
                      created_by=getattr(user, "email", "") or "")
        self.repo.add_media(m)
        self._record(user, "teams.media.note", team_id=team_id)
        return m

    def add_video(self, user: Any, team_id: str, *, url: str = "", data: bytes | None = None,
                  filename: str = "", mime: str = "", title: str = "", match_id: str = "",
                  member_id: str = "", kind: str = "video") -> TeamMedia:
        u, file_id = str(url or "").strip(), ""
        if data is not None:
            if self._files is None:
                raise ValueError("File storage is not configured.")
            file_id = self._uid()
            self._files.save(file_id, data, filename=filename, mime=mime)
        elif not u:
            raise ValueError("A video url or an uploaded file is required.")
        m = TeamMedia(id=self._uid(), team_id=team_id, match_id=str(match_id or ""), kind=kind,
                      member_id=str(member_id or ""), title=str(title or "").strip(), url=u, file_id=file_id,
                      created_by=getattr(user, "email", "") or "")
        self.repo.add_media(m)
        self._record(user, "teams.media.video", team_id=team_id)
        return m

    def add_chart(self, user: Any, team_id: str, data: bytes, mime: str, *, title: str = "",
                  match_id: str = "", member_id: str = "", kind: str = "chart") -> TeamMedia:
        if self._images is None:
            raise ValueError("Image storage is not configured.")
        image_id = self._uid()
        self._images.save(image_id, data, mime=mime)
        m = TeamMedia(id=self._uid(), team_id=team_id, match_id=str(match_id or ""), kind=kind,
                      member_id=str(member_id or ""), title=str(title or "").strip(),
                      image_id=image_id, created_by=getattr(user, "email", "") or "")
        self.repo.add_media(m)
        self._record(user, "teams.media.chart", team_id=team_id)
        return m

    def list_media(self, team_id: str, *, match_id: str | None = None,
                   kind: str | None = None, member_id: str | None = None) -> list[TeamMedia]:
        return self.repo.list_media(team_id, match_id=match_id, kind=kind, member_id=member_id)

    # ---- per-player match portfolio (T6: reuse the existing viz workspace) ----
    def match_player_frame(self, match_row_id: str, player_name: str):
        """The player's event rows for a match — loaded from the match's LINKED dataset by id
        (active-independent) and filtered to this player (+ the match_id). Feeds the existing
        player visualization workspace. None when the match has no linked event data."""
        mt = self.repo.get_match(match_row_id)
        if mt is None or not mt.dataset_id or self._wm is None:
            return None
        try:
            frame = self._wm.dataset_frame(mt.dataset_id)
        except Exception:
            frame = None
        if frame is None or getattr(frame, "empty", True):
            return None
        df = frame
        if mt.match_id and "match_id" in df.columns:
            df = df[df["match_id"].astype(str) == str(mt.match_id)]
        name = str(player_name or "").strip().lower()
        for col in ("player", "player_name", "player.name"):
            if col in df.columns:
                df = df[df[col].astype(str).str.strip().str.lower() == name]
                break
        return df if not getattr(df, "empty", True) else None

    def player_portfolio(self, team_id: str, member_id: str) -> list[TeamMedia]:
        """All charts saved for a roster player across the team's matches (their portfolio)."""
        return self.repo.list_media(team_id, member_id=member_id, kind="chart")

    @staticmethod
    def _match_player_metrics(frame) -> dict[str, Any]:
        """Per-match totals for ONE player's event frame (the unit of both the
        dashboard totals and the match-by-match progression). Pure, honest — reads
        only columns that are present, never fabricates."""
        m = {"events": int(len(frame)), "minutes": 0, "passes": 0, "completed_passes": 0,
             "shots": 0, "goals": 0, "assists": 0}
        columns = {str(c).lower(): c for c in frame.columns}
        minute_col = columns.get("minute")
        if minute_col is not None:
            try:
                values = frame[minute_col].dropna()
                m["minutes"] = int(float(values.max())) if len(values) else 0
            except (TypeError, ValueError):
                pass
        event_col = columns.get("event_type") or columns.get("type")
        events = frame[event_col].astype(str).str.strip().str.lower() if event_col else None
        if events is not None:
            m["passes"] = int(events.isin(["pass", "passing"]).sum())
            m["shots"] = int(events.isin(["shot", "shots"]).sum())
            m["goals"] = int(events.isin(["goal", "goals"]).sum())
        outcome_col = columns.get("outcome") or columns.get("result")
        if events is not None and outcome_col is not None:
            outcomes = frame[outcome_col].astype(str).str.strip().str.lower()
            m["completed_passes"] = int((events.isin(["pass", "passing"]) &
                                         outcomes.isin(["successful", "success", "complete", "completed"])).sum())
            m["goals"] += int((events.isin(["shot", "shots"]) & outcomes.isin(["goal", "scored"])).sum())
        goal_col = columns.get("is_goal")
        if goal_col is not None:
            try:
                m["goals"] += int(frame[goal_col].fillna(False).astype(bool).sum())
            except (TypeError, ValueError):
                pass
        assist_col = columns.get("assist") or columns.get("is_assist")
        if assist_col is not None:
            try:
                m["assists"] = int(frame[assist_col].fillna(False).astype(bool).sum())
            except (TypeError, ValueError):
                pass
        m["pass_completion"] = round(100 * m["completed_passes"] / m["passes"], 1) \
            if m["passes"] else None
        return m

    def player_progression(self, team_id: str, member_id: str) -> list[dict[str, Any]]:
        """The player's per-match metrics across this team's linked matches, oldest
        first — the basis for a development trend (5 matches / 5 datasets → 5 points).
        Only matches whose linked data contains an event for the player are included."""
        member = self.repo.get_member(member_id)
        if member is None:
            return []
        matches = sorted(self.repo.list_matches(team_id),
                         key=lambda mt: (mt.match_date or "", mt.created_at or ""))
        out: list[dict[str, Any]] = []
        for mt in matches:
            if not mt.dataset_id:
                continue
            frame = self.match_player_frame(mt.id, member.player_name)
            if frame is None or getattr(frame, "empty", True):
                continue
            metrics = self._match_player_metrics(frame)
            out.append({"match_id": mt.id, "opponent": mt.opponent,
                        "match_date": mt.match_date, "competition": mt.competition,
                        "dataset_id": mt.dataset_id, "scoreline": mt.scoreline,
                        **metrics})
        return out

    def player_dashboard(self, team_id: str, member_id: str) -> dict[str, Any]:
        """High-level, evidence-backed player totals across this team's linked matches.

        An appearance is counted only when the linked event data contains an event for the
        roster player. This deliberately avoids presenting every team fixture as a player
        appearance when no lineup/minutes data exists.
        """
        matches = self.repo.list_matches(team_id)
        totals: dict[str, Any] = {"team_matches": len(matches), "linked_matches": 0,
                                  "appearances": 0, "minutes": 0, "events": 0,
                                  "passes": 0, "completed_passes": 0, "shots": 0,
                                  "goals": 0, "assists": 0}
        totals["linked_matches"] = sum(1 for mt in matches if mt.dataset_id)
        per_match = self.player_progression(team_id, member_id)
        totals["appearances"] = len(per_match)
        for key in ("events", "minutes", "passes", "completed_passes", "shots",
                    "goals", "assists"):
            totals[key] = sum(int(m.get(key) or 0) for m in per_match)
        totals["pass_completion"] = round(100 * totals["completed_passes"] / totals["passes"], 1) \
            if totals["passes"] else None
        return totals

    def media_bytes(self, media: TeamMedia) -> bytes | None:
        try:
            if media.image_id and self._images is not None:
                return self._images.load(media.image_id)
            if media.file_id and self._files is not None:
                return self._files.load(media.file_id)
        except Exception:
            return None
        return None

    def delete_media(self, user: Any, media_id: str) -> None:
        m = self.repo.get_media(media_id)
        if m is not None:
            if m.image_id and self._images is not None:
                try:
                    self._images.delete(m.image_id)
                except Exception:
                    pass
            if m.file_id and self._files is not None:
                try:
                    self._files.delete(m.file_id)
                except Exception:
                    pass
        self.repo.delete_media(media_id)
        self._record(user, "teams.media.delete", media_id=media_id)

    # ---- team-level aggregates & comparison (T5) ----
    def team_record(self, team_id: str) -> dict[str, Any]:
        """W/D/L record + goals from this team's SCORED matches. Pure aggregation — matches with
        no score recorded are simply not counted (nothing fabricated)."""
        p = w = d = l = gf = ga = 0
        for mt in self.repo.list_matches(team_id):
            if mt.our_score is None or mt.opp_score is None:
                continue
            p += 1
            gf += int(mt.our_score)
            ga += int(mt.opp_score)
            if mt.our_score > mt.opp_score:
                w += 1
            elif mt.our_score < mt.opp_score:
                l += 1
            else:
                d += 1
        return {"played": p, "wins": w, "draws": d, "losses": l, "gf": gf, "ga": ga,
                "gd": gf - ga, "points": w * 3 + d,
                "win_pct": round(100.0 * w / p, 1) if p else 0.0}

    def teams_comparison(self) -> list[dict[str, Any]]:
        """Every team with roster/match counts + record — the T5 team-level comparison."""
        out: list[dict[str, Any]] = []
        for t in self.repo.list():
            out.append({"id": t.id, "name": t.name, "kind": t.kind, "age_group": t.age_group,
                        "players": self.repo.member_count(t.id), **self.team_record(t.id)})
        return out

    def team_summaries(self) -> list[dict[str, Any]]:
        """Teams with roster counts — the T1 aggregate the Teams page lists (team-level
        aggregates/comparisons across rosters build on this in later phases)."""
        out: list[dict[str, Any]] = []
        for t in self.repo.list():
            out.append({"id": t.id, "name": t.name, "kind": t.kind, "age_group": t.age_group,
                        "competition": t.competition, "season": t.season,
                        "members": self.repo.member_count(t.id),
                        "matches": self.repo.match_count(t.id), "crest": bool(t.crest_image_id)})
        return out
