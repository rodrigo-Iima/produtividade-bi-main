from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import re
from typing import Any, Optional
from zoneinfo import ZoneInfo

from clients.clockify_client import ClockifyClient
from database.connection import SessionLocal
from models.bridge_clockify_entry_issue import BridgeClockifyEntryIssue
from models.bridge_clockify_entry_sprint import BridgeClockifyEntrySprint
from models.bridge_clockify_entry_tag import BridgeClockifyEntryTag
from models.bridge_clockify_user_group import BridgeClockifyUserGroup
from models.dim_colaborador import DimColaborador
from models.dim_clockify_group import DimClockifyGroup
from models.dim_papel_tag import DimPapelTag
from models.dim_squad import DimSquad
from models.dim_squad_alias import DimSquadAlias
from models.dim_sprint import DimSprint
from models.dim_tag import DimTag
from models.dim_ticket_jira import DimTicketJira
from models.fato_clockify_entry import FatoClockifyEntry
from models.fato_jira_ticket_sprint import FatoJiraTicketSprint
from providers.tags_provider import normalize_tag


JIRA_ISSUE_KEY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b", re.IGNORECASE)
CAPACITY_GROUP_PATTERN = re.compile(r"^(30|40)h$", re.IGNORECASE)


class ClockifyService:
    """Extract Clockify entries and load the normalized time model."""

    def __init__(self):
        self.client = ClockifyClient()

    def run(self, start_date: Optional[datetime] = None, incremental: bool = True):
        session = SessionLocal()
        try:
            raw_users = self.client.get_users()
            raw_groups = self.client.get_user_groups()
            user_roles, user_squads, capacity_by_user = self._resolve_user_groups(
                raw_groups
            )
            self._load_colaboradores(session, raw_users, user_roles, user_squads)
            group_sync = self._sync_clockify_groups(
                session,
                raw_groups,
                capacity_by_user,
            )
            print(
                f"[ClockifyETL] Synced {group_sync['groups']} groups and "
                f"{group_sync['memberships']} current memberships; "
                f"active_without_capacity={group_sync['active_without_capacity']}"
            )

            start_dt = self._get_start_date(session, start_date, incremental)
            end_dt = datetime.now(timezone.utc)
            start_str = start_dt.strftime("%Y-%m-%dT00:00:00.000Z")
            end_str = end_dt.strftime("%Y-%m-%dT23:59:59.000Z")

            raw_entries = self._extract_entries(start_str, end_str)
            if not raw_entries:
                session.commit()
                print("[ClockifyETL] No completed entries to load.")
                return {
                    "extracted": 0,
                    "transformed": 0,
                    "loaded": 0,
                    "groups": group_sync["groups"],
                    "memberships": group_sync["memberships"],
                }

            extracted_count = len(raw_entries)
            raw_entries = self._deduplicate_entries(raw_entries)

            self._ensure_entry_users(session, raw_entries)
            collaborator_snapshots = self._build_collaborator_snapshot_map(session)
            task_map = self._fetch_and_cache_tasks(raw_entries)
            tag_map = self._ensure_tags(session, raw_entries)
            focus_map = self._get_focus_map(session)
            sprint_map = self._build_jira_sprint_map(session)
            known_issues = {
                row.issue_key for row in session.query(DimTicketJira.issue_key).all()
            }

            entries: list[FatoClockifyEntry] = []
            tags: list[BridgeClockifyEntryTag] = []
            issues: list[BridgeClockifyEntryIssue] = []
            sprint_links: list[BridgeClockifyEntrySprint] = []

            for raw_entry in raw_entries:
                transformed = self._transform_entry(
                    raw_entry,
                    user_roles,
                    task_map,
                    tag_map,
                    focus_map,
                    collaborator_snapshots,
                )
                if transformed is None:
                    continue

                entry, entry_tags = transformed
                entries.append(entry)
                tags.extend(entry_tags)

                description = raw_entry.get("description")
                task_name = entry.task_name
                issue_sources = self._extract_issue_keys_with_sources(
                    description,
                    task_name,
                )
                issue_keys = list(issue_sources)
                valid_issue_keys = [key for key in issue_keys if key in known_issues]
                issues.extend(
                    BridgeClockifyEntryIssue(
                        entry_id=entry.entry_id,
                        issue_key=issue_key,
                        extraction_method=self._extraction_method(
                            issue_sources[issue_key]
                        ),
                    )
                    for issue_key in valid_issue_keys
                )
                sprint_links.extend(
                    self._build_sprint_links(
                        entry,
                        valid_issue_keys,
                        sprint_map,
                    )
                )

            self._replace_entries(session, entries, tags, issues, sprint_links)
            session.commit()
            print(
                f"[ClockifyETL] Loaded {len(entries)} entries, {len(tags)} tag links, "
                f"{len(issues)} issue links and {len(sprint_links)} sprint links"
            )
            return {
                "extracted": extracted_count,
                "transformed": len(entries),
                "loaded": len(entries),
                "tag_links": len(tags),
                "issue_links": len(issues),
                "sprint_links": len(sprint_links),
                "groups": group_sync["groups"],
                "memberships": group_sync["memberships"],
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _extract_entries(self, start_str: str, end_str: str) -> list[dict]:
        entries = []
        page = 1
        while True:
            report = self.client.get_detailed_report(start_str, end_str, page=page)
            page_entries = report.get("timeentries", [])
            if not page_entries:
                break
            entries.extend(page_entries)
            page += 1
        return entries

    @staticmethod
    def _deduplicate_entries(entries: list[dict]) -> list[dict]:
        """Keep one source record per Clockify entry ID before loading."""
        unique: list[dict] = []
        seen: set[str] = set()
        for entry in entries:
            entry_id = entry.get("_id")
            if not entry_id or entry_id in seen:
                continue
            seen.add(entry_id)
            unique.append(entry)
        removed = len(entries) - len(unique)
        if removed:
            print(f"[ClockifyETL] Removed {removed} duplicated report rows")
        return unique

    @staticmethod
    def _classify_clockify_group(name: str) -> tuple[str, Optional[Decimal]]:
        """Classify a Clockify group and extract weekly capacity when applicable."""
        normalized = " ".join((name or "").strip().split())
        capacity_match = CAPACITY_GROUP_PATTERN.fullmatch(
            normalized.replace(" ", "")
        )
        if capacity_match:
            return "capacity", Decimal(capacity_match.group(1))
        if normalized.casefold().startswith("papel -"):
            return "papel", None
        if normalized.casefold().startswith("squad"):
            return "squad", None
        return "other", None

    def _resolve_user_groups(
        self,
        raw_groups: list[dict[str, Any]],
    ) -> tuple[dict[str, str], dict[str, str], dict[str, Decimal]]:
        roles: dict[str, str] = {}
        squads: dict[str, str] = {}
        capacity_by_user: dict[str, Decimal] = {}
        for group in raw_groups:
            name = (group.get("name") or "").strip()
            user_ids = group.get("userIds", [])
            group_type, capacity_hours = self._classify_clockify_group(name)
            if group_type == "papel":
                role = name.split("-", 1)[1].strip()
                for user_id in user_ids:
                    previous = roles.get(user_id)
                    if previous and previous.casefold() != role.casefold():
                        raise ValueError(
                            f"Usuário {user_id} pertence a mais de um Papel: "
                            f"{previous!r} e {role!r}"
                        )
                    roles[user_id] = role
            elif group_type == "squad":
                squad = re.sub(r"^squad\s*-?\s*", "", name, flags=re.IGNORECASE).strip()
                for user_id in user_ids:
                    previous = squads.get(user_id)
                    if previous and previous.casefold() != squad.casefold():
                        raise ValueError(
                            f"Usuário {user_id} pertence a mais de uma Squad: "
                            f"{previous!r} e {squad!r}"
                        )
                    squads[user_id] = squad
            elif group_type == "capacity" and capacity_hours is not None:
                for user_id in user_ids:
                    previous = capacity_by_user.get(user_id)
                    if previous is not None and previous != capacity_hours:
                        raise ValueError(
                            f"Usuário {user_id} pertence a mais de um grupo de capacidade: "
                            f"{previous}h e {capacity_hours}h"
                        )
                    capacity_by_user[user_id] = capacity_hours
        return roles, squads, capacity_by_user

    def _load_colaboradores(
        self,
        session,
        raw_users: list[dict],
        user_roles: dict[str, str],
        user_squads: dict[str, str],
    ) -> None:
        observed_at = datetime.now(timezone.utc)
        session.query(DimColaborador).update(
            {DimColaborador.is_active: False},
            synchronize_session=False,
        )
        aliases = {
            row.nome_bruto.casefold(): row.squad_id
            for row in session.query(DimSquadAlias).filter(
                DimSquadAlias.origem == "clockify"
            ).all()
        }
        transversal = session.query(DimSquad).filter(DimSquad.nome == "Transversal").first()
        transversal_id = transversal.squad_id if transversal else None

        for user in raw_users:
            user_id = user["id"]
            raw_squad = user_squads.get(user_id, "Transversal")
            squad_id = aliases.get(raw_squad.casefold(), transversal_id)
            session.merge(DimColaborador(
                user_id=user_id,
                name=user.get("name") or user_id,
                papel=user_roles.get(user_id),
                squad_id=squad_id,
                is_active=True,
                clockify_last_seen_at=observed_at,
            ))
        session.flush()

    def _sync_clockify_groups(
        self,
        session,
        raw_groups: list[dict[str, Any]],
        capacity_by_user: dict[str, Decimal],
    ) -> dict[str, int]:
        """Synchronize group catalog and current memberships from Clockify."""
        observed_at = datetime.now(timezone.utc)
        known_users = {
            row.user_id for row in session.query(DimColaborador.user_id).all()
        }
        active_users = {
            row.user_id
            for row in session.query(DimColaborador.user_id).filter(
                DimColaborador.is_active.is_(True)
            ).all()
        }

        session.query(DimClockifyGroup).filter(
            DimClockifyGroup.source == "clockify"
        ).update(
            {DimClockifyGroup.is_active: False},
            synchronize_session=False,
        )
        session.query(BridgeClockifyUserGroup).update(
            {BridgeClockifyUserGroup.is_current: False},
            synchronize_session=False,
        )

        group_ids: set[str] = set()
        membership_count = 0
        for group in raw_groups:
            group_id = str(group.get("id") or "").strip()
            name = (group.get("name") or "").strip()
            if not group_id or not name:
                raise ValueError("Grupo Clockify sem id ou nome")

            group_type, capacity_hours = self._classify_clockify_group(name)
            group_ids.add(group_id)
            session.merge(DimClockifyGroup(
                group_id=group_id,
                name=name,
                group_type=group_type,
                capacity_hours_week=capacity_hours,
                source="clockify",
                is_active=True,
                last_seen_at=observed_at,
            ))
        session.flush()

        existing_memberships = {
            (row.user_id, row.group_id): row
            for row in session.query(BridgeClockifyUserGroup).all()
        }
        for group in raw_groups:
            group_id = str(group["id"]).strip()
            for user_id in set(group.get("userIds") or []):
                if user_id not in known_users:
                    continue
                key = (user_id, group_id)
                membership = existing_memberships.get(key)
                if membership is None:
                    session.add(BridgeClockifyUserGroup(
                        user_id=user_id,
                        group_id=group_id,
                        is_current=True,
                        first_seen_at=observed_at,
                        last_seen_at=observed_at,
                    ))
                else:
                    membership.is_current = True
                    membership.last_seen_at = observed_at
                membership_count += 1
        session.flush()

        return {
            "groups": len(group_ids),
            "memberships": membership_count,
            "active_without_capacity": len(active_users - set(capacity_by_user)),
        }

    @staticmethod
    def _build_collaborator_snapshot_map(session) -> dict[str, dict[str, Any]]:
        """Return the current Clockify classification for entry snapshots."""
        rows = session.query(
            DimColaborador.user_id,
            DimColaborador.papel,
            DimColaborador.squad_id,
            DimSquad.nome,
        ).outerjoin(
            DimSquad,
            DimSquad.squad_id == DimColaborador.squad_id,
        ).all()
        return {
            user_id: {
                "papel": papel,
                "squad_id": squad_id,
                "squad_name": squad_name,
            }
            for user_id, papel, squad_id, squad_name in rows
        }

    def _ensure_entry_users(self, session, entries: list[dict]) -> None:
        existing = {
            row.user_id for row in session.query(DimColaborador.user_id).all()
        }
        transversal = session.query(DimSquad).filter(DimSquad.nome == "Transversal").first()
        for entry in entries:
            user_id = entry.get("userId")
            if not user_id or user_id in existing:
                continue
            session.add(DimColaborador(
                user_id=user_id,
                name=entry.get("userName") or user_id,
                papel=None,
                squad_id=transversal.squad_id if transversal else None,
                is_active=False,
            ))
            existing.add(user_id)
        session.flush()

    def _get_start_date(
        self,
        session,
        start_date: Optional[datetime],
        incremental: bool,
    ) -> datetime:
        if start_date:
            return start_date
        if incremental:
            last = session.query(FatoClockifyEntry.entry_date).order_by(
                FatoClockifyEntry.entry_date.desc()
            ).first()
            if last:
                return datetime.combine(last[0], datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=1)
        return datetime(2026, 1, 1, tzinfo=timezone.utc)

    def _fetch_and_cache_tasks(self, entries: list[dict]) -> dict[str, str]:
        project_ids = {entry.get("projectId") for entry in entries if entry.get("projectId")}
        task_map: dict[str, str] = {}
        for project_id in project_ids:
            try:
                for task in self.client.get_project_tasks(project_id):
                    if task.get("id"):
                        task_map[task["id"]] = task.get("name") or ""
            except Exception as exc:
                print(f"[ClockifyETL] Task lookup failed for {project_id}: {exc}")
        return task_map

    def _ensure_tags(self, session, entries: list[dict]) -> dict[str, int]:
        tags = {
            row.nome_normalizado: row.tag_id
            for row in session.query(DimTag).all()
        }
        for entry in entries:
            for raw_tag in entry.get("tags", []):
                name = raw_tag.get("name")
                if not name:
                    continue
                normalized = normalize_tag(name)
                if normalized in tags:
                    continue
                tag = DimTag(nome=name, nome_normalizado=normalized)
                session.add(tag)
                session.flush()
                tags[normalized] = tag.tag_id
        return tags

    def _get_focus_map(self, session) -> dict[tuple[str, int], str]:
        return {
            (row.papel.casefold(), row.tag_id): row.foco
            for row in session.query(DimPapelTag).all()
        }

    def _build_jira_sprint_map(self, session) -> dict[str, list[dict]]:
        rows = session.query(
            FatoJiraTicketSprint.issue_key,
            DimSprint.sprint_id,
            DimSprint.sprint_name,
            DimSprint.sprint_start,
            DimSprint.sprint_end,
        ).join(
            DimSprint, DimSprint.sprint_id == FatoJiraTicketSprint.sprint_id
        ).all()

        result: dict[str, list[dict]] = defaultdict(list)
        for issue_key, sprint_id, name, start, end in rows:
            result[issue_key].append({
                "sprint_id": sprint_id,
                "sprint_name": name,
                "sprint_start": start,
                "sprint_end": end,
            })
        return result

    def _transform_entry(
        self,
        raw: dict,
        user_roles: dict[str, str],
        task_map: dict[str, str],
        tag_map: dict[str, int],
        focus_map: dict[tuple[str, int], str],
        collaborator_snapshots: Optional[dict[str, dict[str, Any]]] = None,
    ) -> Optional[tuple[FatoClockifyEntry, list[BridgeClockifyEntryTag]]]:
        interval = raw.get("timeInterval") or {}
        start_value = interval.get("start")
        end_value = interval.get("end")
        if not start_value or not end_value:
            return None

        started_at = self._parse_iso_date(start_value)
        ended_at = self._parse_iso_date(end_value)
        duration_seconds = max(0, round((ended_at - started_at).total_seconds()))
        entry_id = raw.get("_id")
        user_id = raw.get("userId")
        if not entry_id or not user_id:
            raise ValueError("Clockify entry sem _id ou userId")
        task_id = raw.get("taskId")
        task_name = raw.get("taskName") or task_map.get(task_id)
        collaborator = (collaborator_snapshots or {}).get(user_id, {})
        role = collaborator.get("papel") or user_roles.get(user_id)

        fact = FatoClockifyEntry(
            entry_id=entry_id,
            user_id=user_id,
            description=raw.get("description"),
            project_name=raw.get("projectName") or "Sem Projeto",
            task_id=task_id,
            task_name=task_name,
            started_at=started_at,
            ended_at=ended_at,
            entry_date=started_at.date(),
            entry_date_local=started_at.astimezone(
                ZoneInfo("America/Sao_Paulo")
            ).date(),
            duration_seconds=duration_seconds,
            squad_id_at_entry=collaborator.get("squad_id"),
            squad_name_at_entry=collaborator.get("squad_name"),
            papel_at_entry=role,
        )

        tag_records = []
        seen_tag_ids: set[int] = set()
        for raw_tag in raw.get("tags", []):
            tag_name = raw_tag.get("name")
            if not tag_name:
                continue
            tag_id = tag_map[normalize_tag(tag_name)]
            if tag_id in seen_tag_ids:
                continue
            seen_tag_ids.add(tag_id)
            if not role:
                foco_flag = "Sem Papel Definido"
            elif (role.casefold(), tag_id) in focus_map:
                foco_flag = "Dentro do Foco"
            else:
                foco_flag = "Fora do Foco"
            tag_records.append(BridgeClockifyEntryTag(
                entry_id=entry_id,
                tag_id=tag_id,
                foco_flag=foco_flag,
            ))
        return fact, tag_records

    def _build_sprint_links(
        self,
        entry: FatoClockifyEntry,
        issue_keys: list[str],
        sprint_map: dict[str, list[dict]],
    ) -> list[BridgeClockifyEntrySprint]:
        if not issue_keys:
            return [BridgeClockifyEntrySprint(
                entry_id=entry.entry_id,
                sprint_id=None,
                assignment_status="sem_ticket",
                assignment_reason="jira_issue_not_found",
            )]

        candidates = {}
        for issue_key in issue_keys:
            for sprint in sprint_map.get(issue_key, []):
                if self._interval_overlaps(entry, sprint):
                    candidates[sprint["sprint_id"]] = sprint

        if len(candidates) == 1:
            sprint = next(iter(candidates.values()))
            return [BridgeClockifyEntrySprint(
                entry_id=entry.entry_id,
                sprint_id=sprint["sprint_id"],
                assignment_status="atribuido",
                assignment_reason="sprint_interval",
            )]
        if not candidates:
            return [BridgeClockifyEntrySprint(
                entry_id=entry.entry_id,
                sprint_id=None,
                assignment_status="sem_sprint",
                assignment_reason="no_matching_sprint_interval",
            )]
        return [BridgeClockifyEntrySprint(
            entry_id=entry.entry_id,
            sprint_id=sprint_id,
            assignment_status="ambiguo",
            assignment_reason="multiple_sprint_candidates",
        ) for sprint_id in candidates]

    @staticmethod
    def _interval_overlaps(entry: FatoClockifyEntry, sprint: dict) -> bool:
        if entry.started_at is None or entry.ended_at is None or sprint["sprint_start"] is None:
            return False
        if entry.ended_at <= sprint["sprint_start"]:
            return False
        if sprint["sprint_end"] is not None and entry.started_at >= sprint["sprint_end"]:
            return False
        return True

    def _replace_entries(self, session, entries, tags, issues, sprint_links) -> None:
        if not entries:
            return
        ids = [entry.entry_id for entry in entries]
        session.query(BridgeClockifyEntryTag).filter(
            BridgeClockifyEntryTag.entry_id.in_(ids)
        ).delete(synchronize_session=False)
        session.query(BridgeClockifyEntryIssue).filter(
            BridgeClockifyEntryIssue.entry_id.in_(ids)
        ).delete(synchronize_session=False)
        session.query(BridgeClockifyEntrySprint).filter(
            BridgeClockifyEntrySprint.entry_id.in_(ids)
        ).delete(synchronize_session=False)
        session.query(FatoClockifyEntry).filter(
            FatoClockifyEntry.entry_id.in_(ids)
        ).delete(synchronize_session=False)

        session.add_all(entries)
        session.flush()
        session.add_all(tags)
        session.add_all(issues)
        session.add_all(sprint_links)

    @staticmethod
    def _extract_issue_keys(*texts: Optional[str]) -> list[str]:
        return list(ClockifyService._extract_issue_keys_with_sources(*texts))

    @staticmethod
    def _extract_issue_keys_with_sources(
        *texts: Optional[str],
    ) -> dict[str, set[str]]:
        sources: dict[str, set[str]] = defaultdict(set)
        source_names = ("description", "task_name")
        for index, value in enumerate(texts):
            if not value:
                continue
            for match in JIRA_ISSUE_KEY_PATTERN.findall(value):
                normalized = match.upper()
                source = source_names[index] if index < len(source_names) else "other"
                sources[normalized].add(source)
        return sources

    @staticmethod
    def _extraction_method(sources: set[str]) -> str:
        if sources == {"description"}:
            return "description"
        if sources == {"task_name"}:
            return "task_name"
        if "description" in sources and "task_name" in sources:
            return "description_and_task"
        return "legacy"

    @staticmethod
    def _parse_iso_date(value: str) -> datetime:
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        elif re.search(r"[+-]\d{4}$", normalized):
            normalized = normalized[:-5] + normalized[-5:-2] + ":" + normalized[-2:]
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
