from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import re
from threading import Lock

from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from clients.jira_client import JiraClient
from config.settings import JIRA_SPRINT_FIELD
from database.connection import SessionLocal
from models.dim_sprint import DimSprint
from models.dim_ticket_jira import DimTicketJira
from models.jira_sprint_changelog import JiraSprintChangelog
from models.fato_jira_ticket_sprint import FatoJiraTicketSprint
from models.fato_jira_status_transicao import FatoJiraStatusTransicao
from models.etl_source_state import EtlSourceState
from etl.sprint_scope import SPRINT_START_AFTER, sprint_is_in_scope


class SprintChangelogETL:
    """Extract one Jira changelog and materialize sprint/status events.

    Jira returns sprint and status changes in the same changelog response.  A
    worker therefore fetches it exactly once per issue and fans the response
    out to the two event facts.  Per-issue ``etl_source_state`` rows make a
    backfill resumable without deleting the historical facts.
    """

    SPRINT_FIELD_ID = JIRA_SPRINT_FIELD

    SOURCE_PREFIX = "jira_changelog:"
    PIPELINE_NAME = "jira_sprint_and_status"
    DEFAULT_PROJECTS = ("ZGT", "ZG", "ZGTN", "SRE")

    def __init__(self, max_workers: int = 8, client: JiraClient | None = None):
        self.client = client or JiraClient()
        self.max_workers = max_workers
        self._sprint_metadata_cache: dict[int, dict] = {}
        self._sprint_metadata_lock = Lock()

    def run(
        self,
        incremental: bool = True,
        issue_keys: list[str] | None = None,
        issue_types: tuple[str, ...] | list[str] | None = None,
        resume: bool = False,
        projects: tuple[str, ...] | list[str] | None = None,
    ) -> int:
        session = SessionLocal()
        try:
            issue_keys = self._get_issue_keys(
                session,
                incremental,
                issue_keys,
                issue_types=issue_types,
                resume=resume,
                projects=projects,
            )
        finally:
            session.close()

        if not issue_keys:
            materialized = materialize_historical_sprint_relations()
            if materialized:
                print(
                    f"[SprintChangelogETL] Materialized {materialized} historical "
                    "ticket/sprint relations"
                )
            print("[SprintChangelogETL] No issues to process.")
            return materialized

        inserted = 0
        failed = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_issue, issue_key): issue_key
                for issue_key in issue_keys
            }
            for future in as_completed(futures):
                issue_key = futures[future]
                try:
                    inserted += future.result()
                except Exception as exc:
                    failed += 1
                    print(f"[SprintChangelogETL] Failed {issue_key}: {exc}")

        materialized = materialize_historical_sprint_relations()
        if materialized:
            print(
                f"[SprintChangelogETL] Materialized {materialized} historical "
                "ticket/sprint relations"
            )
        print(f"[SprintChangelogETL] Done. Inserted: {inserted}, Failed: {failed}")
        if failed:
            raise RuntimeError(f"{failed} Jira changelog requests failed")
        return inserted

    def _get_issue_keys(
        self,
        session,
        incremental: bool,
        issue_keys: list[str] | None = None,
        issue_types: tuple[str, ...] | list[str] | None = None,
        resume: bool = False,
        projects: tuple[str, ...] | list[str] | None = None,
    ) -> list[str]:
        # Process every 2026 ticket when no upstream change list is supplied.
        # A ticket can have historical sprint changes while its current Jira
        # field is empty or points to another sprint. The orchestrator passes
        # the Jira extraction list to keep normal incremental runs efficient.
        query = select(DimTicketJira.issue_key)
        # The initial Epic scope starts in 2026.  An explicit child list is a
        # deliberate audit request, however, and may contain a child created
        # before that date because its Epic is in scope.
        if issue_keys is None:
            query = query.where(DimTicketJira.created_at >= SPRINT_START_AFTER)
        project_scope = tuple(
            str(project).strip().upper()
            for project in (projects or self.DEFAULT_PROJECTS)
            if str(project).strip()
        )
        if project_scope:
            query = query.where(DimTicketJira.project_key.in_(project_scope))
        if issue_types:
            normalized_types = tuple(
                str(issue_type).strip().casefold()
                for issue_type in issue_types
                if str(issue_type).strip()
            )
            if normalized_types:
                query = query.where(
                    func.lower(DimTicketJira.issue_type_name).in_(normalized_types)
                )
        failed_issue_keys = select(JiraSprintChangelog.issue_key).where(
            JiraSprintChangelog.processing_status == "failed"
        )
        if issue_keys is not None:
            query = query.where(or_(
                DimTicketJira.issue_key.in_(issue_keys),
                DimTicketJira.issue_key.in_(failed_issue_keys),
            ))

        selected = [row[0] for row in session.execute(query).all()]
        if not resume or not selected:
            return selected

        # Successful source states are durable checkpoints.  Failed and
        # not-found states remain eligible so an operator can retry explicitly.
        successful = {
            source_name[len(self.SOURCE_PREFIX):]
            for source_name, in session.execute(
                select(EtlSourceState.source_name).where(
                    EtlSourceState.source_name.like(f"{self.SOURCE_PREFIX}%"),
                    EtlSourceState.status == "success",
                )
            ).all()
            if source_name.startswith(self.SOURCE_PREFIX)
        }
        return [issue_key for issue_key in selected if issue_key not in successful]

    def _process_issue(self, issue_key: str) -> int:
        session = SessionLocal()
        try:
            self._set_source_state(session, issue_key, status="running")
            session.commit()
            histories = self.client.get_issue_changelog(issue_key)
            sprint_changes = self._extract_sprint_changes(histories)
            status_transitions = self._extract_status_transitions(issue_key, histories)
            sprint_ids = self._load_sprint_ids(session)

            resolved_changes = []
            for change in sprint_changes:
                sprint_id = change.get("sprint_id") or self._match_sprint_id(
                    change.get("sprint_name"), sprint_ids
                )
                if sprint_id is not None:
                    in_scope = self._ensure_sprint_dimension(
                        session,
                        sprint_id=int(sprint_id),
                        sprint_name=change.get("sprint_name"),
                    )
                    if not in_scope:
                        continue
                else:
                    continue
                resolved_changes.append({**change, "sprint_id": int(sprint_id)})

            session.query(JiraSprintChangelog).filter(
                JiraSprintChangelog.issue_key == issue_key
            ).delete(synchronize_session=False)

            records = []
            for change in resolved_changes:
                records.append(JiraSprintChangelog(
                    issue_key=issue_key,
                    sprint_id=change["sprint_id"],
                    change_type=change["change_type"],
                    changed_at=change["changed_at"],
                    fetched_at=datetime.now(timezone.utc),
                    processing_status="processed",
                ))

            # Materialize historical ticket × sprint relationships discovered
            # only in the changelog. The Jira ETL handles current sprint rows;
            # this step completes the historical fact without overwriting
            # planning values already calculated for existing relations.
            historical_sprint_ids = {
                change["sprint_id"] for change in resolved_changes
            }
            for sprint_id in historical_sprint_ids:
                relation = session.get(
                    FatoJiraTicketSprint,
                    {"issue_key": issue_key, "sprint_id": sprint_id},
                )
                if relation is None:
                    session.add(FatoJiraTicketSprint(
                        issue_key=issue_key,
                        sprint_id=sprint_id,
                    ))

            session.add_all(records)
            self._upsert_status_transitions(session, issue_key, status_transitions)
            self._set_source_state(
                session,
                issue_key,
                status="success",
                rows_processed=len(sprint_changes) + len(status_transitions),
                last_record_at=self._last_record_at(
                    sprint_changes, status_transitions
                ),
                watermark_value=str(len(histories)),
            )
            session.commit()
            return len(records)
        except Exception as exc:
            session.rollback()
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            is_not_found = status_code == 404
            session.query(JiraSprintChangelog).filter(
                JiraSprintChangelog.issue_key == issue_key
            ).delete(synchronize_session=False)
            if is_not_found:
                session.query(FatoJiraStatusTransicao).filter(
                    FatoJiraStatusTransicao.issue_key == issue_key
                ).update({"source_present": False}, synchronize_session=False)
            session.add(JiraSprintChangelog(
                issue_key=issue_key,
                sprint_id=None,
                change_type="added",
                changed_at=datetime.now(timezone.utc),
                fetched_at=datetime.now(timezone.utc),
                # Keep the historical ticket in the warehouse when Jira no
                # longer exposes it. A 404 is a terminal source state, not an
                # operational ETL failure that should poison every backfill.
                processing_status="not_found" if is_not_found else "failed",
                error_message=str(exc),
            ))
            self._set_source_state(
                session,
                issue_key,
                # ``not_found`` is retained in the sprint cache as a source
                # outcome, while the checkpoint contract uses its finite
                # status vocabulary and keeps the item retryable.
                status="failed",
                error_code="not_found" if is_not_found else type(exc).__name__,
                error_message=str(exc),
            )
            session.commit()
            if is_not_found:
                print(f"[SprintChangelogETL] Not found in Jira: {issue_key}")
                return 0
            raise
        finally:
            session.close()

    def _ensure_sprint_dimension(
        self,
        session,
        sprint_id: int,
        sprint_name: str | None,
    ) -> bool:
        """Create a historical sprint before inserting its changelog row.

        A sprint can disappear from the current Jira sprint field after it is
        closed or archived, while its ID remains present in changelog events.
        The PostgreSQL upsert is intentionally conflict-safe because several
        changelog workers may discover the same historical sprint at once.
        """
        existing = session.get(DimSprint, sprint_id)
        has_complete_metadata = existing is not None and all((
            existing.sprint_start is not None,
            existing.sprint_end is not None,
            existing.sprint_state is not None,
            (existing.sprint_state or "").casefold() != "closed"
            or existing.sprint_completed_at is not None,
        ))
        metadata = {} if has_complete_metadata else self._get_sprint_metadata(sprint_id)

        name = (
            metadata.get("name")
            or sprint_name
            or (existing.sprint_name if existing is not None else None)
            or f"Sprint {sprint_id}"
        ).strip()[:200]
        start = self._parse_date(metadata.get("startDate")) if metadata.get("startDate") else None
        end = self._parse_date(metadata.get("endDate")) if metadata.get("endDate") else None
        completed_at = (
            self._parse_date(metadata.get("completeDate"))
            if metadata.get("completeDate")
            else None
        )
        state = metadata.get("state")
        origin_board_id = self._parse_int(
            metadata.get("originBoardId") or metadata.get("boardId")
        )
        start = start or (existing.sprint_start if existing is not None else None)
        origin_board_id = origin_board_id or (
            existing.origin_board_id if existing is not None else None
        )
        state = state or (existing.sprint_state if existing is not None else None)

        if not sprint_is_in_scope(start, state):
            print(f"[SprintChangelogETL] Ignoring out-of-scope sprint {sprint_id}")
            return False

        statement = pg_insert(DimSprint).values(
            sprint_id=sprint_id,
            sprint_name=name or f"Sprint {sprint_id}",
            sprint_start=start,
            sprint_end=end,
            sprint_completed_at=completed_at,
            sprint_state=state,
            origin_board_id=origin_board_id,
        )
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=[DimSprint.sprint_id],
            set_={
                "sprint_name": case(
                    (DimSprint.sprint_name.like(f"Sprint {sprint_id}"), excluded.sprint_name),
                    else_=DimSprint.sprint_name,
                ),
                "sprint_start": func.coalesce(DimSprint.sprint_start, excluded.sprint_start),
                "sprint_end": func.coalesce(DimSprint.sprint_end, excluded.sprint_end),
                "sprint_completed_at": func.coalesce(
                    excluded.sprint_completed_at,
                    DimSprint.sprint_completed_at,
                ),
                "sprint_state": func.coalesce(DimSprint.sprint_state, excluded.sprint_state),
                "origin_board_id": func.coalesce(
                    DimSprint.origin_board_id, excluded.origin_board_id
                ),
            },
        )
        session.execute(statement)
        return True

    def _get_sprint_metadata(self, sprint_id: int) -> dict:
        """Fetch each missing sprint once across concurrent issue workers."""
        with self._sprint_metadata_lock:
            if sprint_id in self._sprint_metadata_cache:
                return self._sprint_metadata_cache[sprint_id]
            try:
                metadata = self.client.get_sprint(sprint_id) or {}
            except Exception as exc:
                print(
                    f"[SprintChangelogETL] Metadata unavailable for sprint "
                    f"{sprint_id}: {exc}. Continuing with changelog data."
                )
                metadata = {}
            self._sprint_metadata_cache[sprint_id] = metadata
            return metadata

    @staticmethod
    def _parse_int(value) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _load_sprint_ids(session) -> dict[str, int]:
        return {
            row.sprint_name.casefold(): row.sprint_id
            for row in session.query(DimSprint).all()
        }

    @staticmethod
    def _match_sprint_id(name: str | None, sprint_ids: dict[str, int]) -> int | None:
        if not name:
            return None
        normalized = name.strip().casefold()
        for sprint_name, sprint_id in sprint_ids.items():
            if normalized == sprint_name or normalized in sprint_name or sprint_name in normalized:
                return sprint_id
        return None

    def _extract_sprint_changes(self, histories: list[dict]) -> list[dict]:
        changes = []
        for history in histories:
            created = history.get("created")
            if not created:
                continue
            changed_at = self._parse_date(created)
            for item in history.get("items", []):
                if item.get("fieldId") != self.SPRINT_FIELD_ID and item.get("field") != "Sprint":
                    continue

                for change_type, id_value, name_value in (
                    ("added", item.get("to"), item.get("toString")),
                    ("removed", item.get("from"), item.get("fromString")),
                ):
                    for sprint in self._parse_sprint_change(id_value, name_value):
                        changes.append({
                            **sprint,
                            "change_type": change_type,
                            "changed_at": changed_at,
                        })
        return changes

    def _extract_status_transitions(
        self,
        issue_key: str,
        histories: list[dict],
    ) -> list[dict]:
        """Extract every status event from the already-fetched changelog."""
        transitions: list[dict] = []
        for history_index, history in enumerate(histories):
            created = history.get("created")
            if not created:
                continue
            transition_at = self._parse_date(created)
            author = history.get("author") or {}
            history_id = str(history.get("id") or "").strip()
            for item_index, item in enumerate(history.get("items", [])):
                if item.get("fieldId") != "status" and item.get("field") != "status":
                    continue
                transition_key = self._transition_key(
                    issue_key,
                    history_id,
                    item_index,
                    transition_at,
                    item,
                    history_index=history_index,
                )
                transitions.append({
                    "issue_key": issue_key,
                    "transition_key": transition_key,
                    "transition_at": transition_at,
                    "from_status_id": self._as_text(item.get("from")),
                    "from_status_name": self._as_text(item.get("fromString")),
                    "to_status_id": self._as_text(item.get("to")),
                    "to_status_name": self._as_text(item.get("toString")),
                    "author_account_id": self._as_text(
                        author.get("accountId") or author.get("key")
                    ),
                    "author_name": self._as_text(
                        author.get("displayName") or author.get("name")
                    ),
                    "source_present": True,
                })
        return transitions

    @staticmethod
    def _as_text(value) -> str | None:
        if value is None or value == "":
            return None
        return str(value)

    @staticmethod
    def _transition_key(
        issue_key: str,
        history_id: str,
        item_index: int,
        transition_at: datetime,
        item: dict,
        history_index: int | None = None,
    ) -> str:
        if history_id:
            return f"jira:{history_id}:{item_index}"
        raw = "|".join([
            issue_key,
            transition_at.isoformat(),
            str(history_index if history_index is not None else ""),
            str(item_index),
            str(item.get("from") or ""),
            str(item.get("to") or ""),
            str(item.get("fromString") or ""),
            str(item.get("toString") or ""),
        ])
        return f"hash:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    def _upsert_status_transitions(
        self,
        session,
        issue_key: str,
        transitions: list[dict],
    ) -> None:
        # A successful full changelog fetch is the source-of-truth snapshot
        # for this issue.  Keep disappeared events auditable, but make them
        # invisible to current-state views through source_present.
        session.query(FatoJiraStatusTransicao).filter(
            FatoJiraStatusTransicao.issue_key == issue_key
        ).update({"source_present": False}, synchronize_session=False)
        if not transitions:
            return

        now = datetime.now(timezone.utc)
        unique_transitions = {
            transition["transition_key"]: transition
            for transition in transitions
        }
        values = [
            {
                **transition,
                "loaded_at": now,
            }
            for transition in unique_transitions.values()
        ]
        statement = pg_insert(FatoJiraStatusTransicao).values(values)
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=[
                FatoJiraStatusTransicao.issue_key,
                FatoJiraStatusTransicao.transition_key,
            ],
            set_={
                "transition_at": excluded.transition_at,
                "from_status_id": excluded.from_status_id,
                "from_status_name": excluded.from_status_name,
                "to_status_id": excluded.to_status_id,
                "to_status_name": excluded.to_status_name,
                "author_account_id": excluded.author_account_id,
                "author_name": excluded.author_name,
                "source_present": True,
                "loaded_at": now,
            },
        )
        session.execute(statement)

    def _set_source_state(
        self,
        session,
        issue_key: str,
        status: str,
        rows_processed: int = 0,
        error_code: str | None = None,
        error_message: str | None = None,
        last_record_at: datetime | None = None,
        watermark_value: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        source_name = f"{self.SOURCE_PREFIX}{issue_key}"[:80]
        values = {
            "source_name": source_name,
            "pipeline_name": self.PIPELINE_NAME,
            "last_attempt_at": now,
            "status": status,
            "rows_processed": rows_processed,
            "error_code": error_code,
            "error_message": error_message,
            "watermark_at": last_record_at,
            "last_record_at": last_record_at,
            "watermark_value": watermark_value,
            "updated_at": now,
        }
        if status == "success":
            values["last_success_at"] = now
        statement = pg_insert(EtlSourceState).values(values)
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=[EtlSourceState.source_name],
            set_={
                "pipeline_name": excluded.pipeline_name,
                "last_attempt_at": excluded.last_attempt_at,
                "status": excluded.status,
                "rows_processed": excluded.rows_processed,
                "error_code": excluded.error_code,
                "error_message": excluded.error_message,
                "watermark_at": (
                    excluded.watermark_at
                    if status == "success"
                    else EtlSourceState.watermark_at
                ),
                "last_record_at": excluded.last_record_at,
                "watermark_value": excluded.watermark_value,
                "updated_at": excluded.updated_at,
                "last_success_at": (
                    excluded.last_success_at
                    if status == "success"
                    else EtlSourceState.last_success_at
                ),
            },
        )
        session.execute(statement)

    @staticmethod
    def _last_record_at(
        sprint_changes: list[dict],
        status_transitions: list[dict],
    ) -> datetime | None:
        timestamps = [
            change.get("changed_at") for change in sprint_changes
        ] + [
            transition.get("transition_at") for transition in status_transitions
        ]
        timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
        return max(timestamps) if timestamps else None

    @staticmethod
    def _parse_sprint_change(id_value, name_value: str | None) -> list[dict]:
        direct_id = int(id_value) if id_value and str(id_value).isdigit() else None
        name = (name_value or "").strip()
        if not name and direct_id is None:
            return []

        # Jira can serialize a bulk sprint move as a comma-separated list of
        # sprint descriptors. Keep one normalized event per sprint so the
        # later join can use the sprint ID whenever Jira provides it.
        descriptors = re.findall(r"([^\[]*?)\s*\[([^\]]+)\]", name)
        if descriptors:
            parsed = []
            for label, metadata in descriptors:
                sprint_id = None
                for part in metadata.split(","):
                    key, separator, value = part.partition("=")
                    if separator and key.strip() == "id" and value.strip().isdigit():
                        sprint_id = int(value.strip())
                        break
                clean_name = label.strip(" ,") or None
                if sprint_id is not None or clean_name:
                    parsed.append({"sprint_id": sprint_id, "sprint_name": clean_name})
            if parsed:
                if direct_id is not None and len(parsed) == 1 and parsed[0]["sprint_id"] is None:
                    parsed[0]["sprint_id"] = direct_id
                return parsed

        if direct_id is not None:
            return [{"sprint_id": direct_id, "sprint_name": name or None}]
        return [{"sprint_id": None, "sprint_name": name or None}]

    @staticmethod
    def _parse_date(value: str) -> datetime:
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        elif re.search(r"[+-]\d{4}$", normalized):
            normalized = normalized[:-5] + normalized[-5:-2] + ":" + normalized[-2:]
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)


def materialize_historical_sprint_relations(session=None) -> int:
    """Backfill missing ticket × sprint facts from processed changelog rows."""
    owns_session = session is None
    if owns_session:
        session = SessionLocal()

    try:
        source = select(
            JiraSprintChangelog.issue_key,
            JiraSprintChangelog.sprint_id,
        ).join(
            DimTicketJira,
            DimTicketJira.issue_key == JiraSprintChangelog.issue_key,
        ).join(
            DimSprint,
            DimSprint.sprint_id == JiraSprintChangelog.sprint_id,
        ).outerjoin(
            FatoJiraTicketSprint,
            (FatoJiraTicketSprint.issue_key == JiraSprintChangelog.issue_key)
            & (FatoJiraTicketSprint.sprint_id == JiraSprintChangelog.sprint_id),
        ).where(
            JiraSprintChangelog.processing_status == "processed",
            JiraSprintChangelog.sprint_id.is_not(None),
            FatoJiraTicketSprint.issue_key.is_(None),
        ).distinct()
        statement = pg_insert(FatoJiraTicketSprint).from_select(
            ["issue_key", "sprint_id"], source
        ).on_conflict_do_nothing(
            index_elements=[
                FatoJiraTicketSprint.issue_key,
                FatoJiraTicketSprint.sprint_id,
            ]
        )
        result = session.execute(statement)
        if owns_session:
            session.commit()
        return result.rowcount or 0
    except Exception:
        if owns_session:
            session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def run_sprint_changelog_etl(
    incremental: bool = True,
    max_workers: int = 8,
    issue_keys: list[str] | None = None,
    issue_types: tuple[str, ...] | list[str] | None = None,
    resume: bool = False,
    projects: tuple[str, ...] | list[str] | None = None,
) -> int:
    return SprintChangelogETL(max_workers=max_workers).run(
        incremental=incremental,
        issue_keys=issue_keys,
        issue_types=issue_types,
        resume=resume,
        projects=projects,
    )
