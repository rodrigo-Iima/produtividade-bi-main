from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
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
from etl.sprint_scope import SPRINT_START_AFTER, sprint_is_in_scope


class SprintChangelogETL:
    """Extract and replace sprint changelog rows per updated Jira ticket."""

    SPRINT_FIELD_ID = JIRA_SPRINT_FIELD

    def __init__(self, max_workers: int = 8):
        self.client = JiraClient()
        self.max_workers = max_workers
        self._sprint_metadata_cache: dict[int, dict] = {}
        self._sprint_metadata_lock = Lock()

    def run(
        self,
        incremental: bool = True,
        issue_keys: list[str] | None = None,
    ) -> int:
        session = SessionLocal()
        try:
            issue_keys = self._get_issue_keys(session, incremental, issue_keys)
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
    ) -> list[str]:
        # Process every 2026 ticket when no upstream change list is supplied.
        # A ticket can have historical sprint changes while its current Jira
        # field is empty or points to another sprint. The orchestrator passes
        # the Jira extraction list to keep normal incremental runs efficient.
        query = select(DimTicketJira.issue_key).where(
            DimTicketJira.created_at >= SPRINT_START_AFTER
        )
        failed_issue_keys = select(JiraSprintChangelog.issue_key).where(
            JiraSprintChangelog.processing_status == "failed"
        )
        if issue_keys is not None:
            query = query.where(or_(
                DimTicketJira.issue_key.in_(issue_keys),
                DimTicketJira.issue_key.in_(failed_issue_keys),
            ))

        return [row[0] for row in session.execute(query).all()]

    def _process_issue(self, issue_key: str) -> int:
        session = SessionLocal()
        try:
            histories = self.client.get_issue_changelog(issue_key)
            sprint_changes = self._extract_sprint_changes(histories)
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
            session.commit()
            return len(records)
        except Exception as exc:
            session.rollback()
            session.query(JiraSprintChangelog).filter(
                JiraSprintChangelog.issue_key == issue_key
            ).delete(synchronize_session=False)
            session.add(JiraSprintChangelog(
                issue_key=issue_key,
                sprint_id=None,
                change_type="added",
                changed_at=datetime.now(timezone.utc),
                fetched_at=datetime.now(timezone.utc),
                processing_status="failed",
                error_message=str(exc),
            ))
            session.commit()
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
        state = metadata.get("state")
        start = start or (existing.sprint_start if existing is not None else None)
        state = state or (existing.sprint_state if existing is not None else None)

        if not sprint_is_in_scope(start, state):
            print(f"[SprintChangelogETL] Ignoring out-of-scope sprint {sprint_id}")
            return False

        statement = pg_insert(DimSprint).values(
            sprint_id=sprint_id,
            sprint_name=name or f"Sprint {sprint_id}",
            sprint_start=start,
            sprint_end=end,
            sprint_state=state,
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
                "sprint_state": func.coalesce(DimSprint.sprint_state, excluded.sprint_state),
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
) -> int:
    return SprintChangelogETL(max_workers=max_workers).run(
        incremental=incremental,
        issue_keys=issue_keys,
    )
