"""Load the Jira Epic -> ticket -> subtask hierarchy.

The productivity ETL intentionally keeps this loader independent from the
Clockify/Flow pipeline. It can therefore be run as a project backfill later,
while the normalized bridge and source-presence columns are already available
for reconciliation.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import requests
from sqlalchemy import or_

from clients.jira_client import JiraClient
from config.settings import JIRA_EPIC_LINK_FIELD
from database.connection import SessionLocal
from etl.jira import JiraService
from models.bridge_jira_issue_parent import BridgeJiraIssueParent
from models.dim_ticket_jira import DimTicketJira
from models.dim_sprint import DimSprint


DEFAULT_PROJECTS = ("ZGT", "ZG", "ZGTN", "SRE")
DEFAULT_EPIC_START_DATE = "2026-01-01"


class JiraHierarchyService:
    """Extract and reconcile project hierarchy at child -> parent grain."""

    def __init__(
        self,
        client: JiraClient | None = None,
        session_factory=SessionLocal,
    ):
        self.client = client or JiraClient()
        self.session_factory = session_factory
        self.ticket_service = JiraService(client=self.client)

    def run(
        self,
        projects: Iterable[str] | None = None,
        epic_start_date: str = DEFAULT_EPIC_START_DATE,
        updated_since: datetime | None = None,
        reconcile_absence: bool = True,
    ) -> dict[str, int]:
        """Load Epics and all descendants, preserving missing source rows."""
        project_list = self._normalize_projects(projects)
        epic_jql = self.build_epic_jql(
            project_list,
            epic_start_date,
            updated_since=updated_since,
        )
        epics = self.client.search(
            jql=epic_jql,
            fields=JiraService.FIELDS,
        )
        epic_search_metrics = dict(self.client.last_metrics)

        records: dict[str, dict[str, Any]] = {}
        edges: dict[tuple[str, str, str], BridgeJiraIssueParent] = {}
        current_epic_keys: set[str] = set()
        children_count = 0
        subtasks_count = 0
        child_pages = 0
        subtask_pages = 0
        retries = epic_search_metrics.get("retries", 0)

        for epic in epics:
            epic_key = epic.get("key")
            if not epic_key:
                continue
            current_epic_keys.add(epic_key)
            self._store_record(records, self.ticket_service._transform_issue(epic))

            children, metrics = self._search_children(epic_key, include_legacy=True)
            child_pages += metrics.get("pages", 0)
            retries += metrics.get("retries", 0)
            children_count += len(children)

            for child, relationship_type in children:
                child_key = child.get("key")
                if not child_key:
                    continue
                self._store_record(
                    records,
                    self.ticket_service._transform_issue(
                        child,
                        forced_parent_key=epic_key,
                        forced_relationship_type=relationship_type,
                    ),
                )
                edges[(child_key, epic_key, relationship_type)] = (
                    self._edge(child_key, epic_key, relationship_type)
                )

                subtasks, metrics = self._search_children(
                    child_key,
                    include_legacy=False,
                )
                subtask_pages += metrics.get("pages", 0)
                retries += metrics.get("retries", 0)
                subtasks_count += len(subtasks)
                for subtask, subtask_relationship in subtasks:
                    subtask_key = subtask.get("key")
                    if not subtask_key:
                        continue
                    self._store_record(
                        records,
                        self.ticket_service._transform_issue(
                            subtask,
                            forced_parent_key=child_key,
                            forced_relationship_type=subtask_relationship,
                        ),
                    )
                    edges[(subtask_key, child_key, subtask_relationship)] = (
                        self._edge(
                            subtask_key,
                            child_key,
                            subtask_relationship,
                        )
                    )

        observed_keys = set(records)
        marked_absent = self._load(
            records.values(),
            edges.values(),
            project_list,
            current_epic_keys,
            observed_keys,
            reconcile_absence=reconcile_absence,
        )
        pages_processed = (
            epic_search_metrics.get("pages", 0)
            + child_pages
            + subtask_pages
        )
        result = {
            "epics_extracted": len(current_epic_keys),
            "children_extracted": children_count,
            "subtasks_extracted": subtasks_count,
            "issues_loaded": len(observed_keys),
            "relations_loaded": len(edges),
            "source_rows_marked_absent": marked_absent,
            "pages_processed": pages_processed,
            "retries": retries,
            "incremental": updated_since is not None,
        }
        print(
            "[JiraHierarchyETL] "
            f"Epics={result['epics_extracted']}, "
            f"children={result['children_extracted']}, "
            f"subtasks={result['subtasks_extracted']}, "
            f"relations={result['relations_loaded']}, "
            f"pages={result['pages_processed']}, "
            f"retries={result['retries']}"
        )
        return result

    @staticmethod
    def build_epic_jql(
        projects: Iterable[str],
        epic_start_date: str = DEFAULT_EPIC_START_DATE,
        updated_since: datetime | None = None,
    ) -> str:
        project_clause = ", ".join(projects)
        jql = (
            f"project in ({project_clause}) AND issuetype = Epic "
            f'AND created >= "{epic_start_date}" ORDER BY created ASC'
        )
        if updated_since is not None:
            updated_at = updated_since.astimezone(timezone.utc).strftime(
                "%Y-%m-%d %H:%M"
            )
            jql = (
                f"project in ({project_clause}) AND issuetype = Epic "
                f'AND created >= "{epic_start_date}" '
                f'AND updated >= "{updated_at}" ORDER BY updated ASC'
            )
        return jql

    def _search_children(
        self,
        parent_key: str,
        include_legacy: bool,
    ) -> tuple[list[tuple[dict, str]], dict[str, int]]:
        """Search direct children, falling back when Epic Link is unsupported."""
        queries: list[tuple[str, str]] = [
            (f'parent = "{self._quote(parent_key)}"', "parent")
        ]
        if include_legacy and JIRA_EPIC_LINK_FIELD:
            queries.append(
                (
                    f'{self._field_expression(JIRA_EPIC_LINK_FIELD)} = '
                    f'"{self._quote(parent_key)}"',
                    "epic_link",
                )
            )

        by_key: dict[str, tuple[dict, str]] = {}
        metrics = {"pages": 0, "retries": 0}
        for jql, relationship_type in queries:
            try:
                issues = self.client.search(
                    jql=jql,
                    fields=JiraService.FIELDS,
                )
            except requests.HTTPError as exc:
                # A Jira instance without the configured legacy field returns
                # HTTP 400. The modern parent search remains authoritative.
                if relationship_type == "epic_link" and self._status_code(exc) == 400:
                    print(
                        f"[JiraHierarchyETL] Legacy Epic Link unavailable for "
                        f"{parent_key}; continuing with parent field"
                    )
                    continue
                raise

            operation_metrics = self.client.last_metrics
            metrics["pages"] += operation_metrics.get("pages", 0)
            metrics["retries"] += operation_metrics.get("retries", 0)
            for issue in issues:
                issue_key = issue.get("key")
                if not issue_key:
                    continue
                existing = by_key.get(issue_key)
                # Prefer the native parent relation when both queries return
                # the same ticket, retaining Epic Link only as fallback.
                if existing is None or existing[1] == "epic_link":
                    by_key[issue_key] = (issue, relationship_type)

        return list(by_key.values()), metrics

    def _load(
        self,
        records: Iterable[dict[str, Any]],
        edges: Iterable[BridgeJiraIssueParent],
        projects: list[str],
        current_epic_keys: set[str],
        observed_keys: set[str],
        reconcile_absence: bool = True,
    ) -> int:
        session = self.session_factory()
        try:
            candidate_keys = (
                self._source_reconciliation_keys(
                    session,
                    projects,
                    current_epic_keys,
                    include_all_epics=reconcile_absence,
                )
                if observed_keys
                else set()
            )
            absent_keys = candidate_keys - observed_keys
            if candidate_keys:
                session.query(DimTicketJira).filter(
                    DimTicketJira.issue_key.in_(candidate_keys)
                ).update(
                    {DimTicketJira.source_present: False},
                    synchronize_session=False,
                )
                session.query(BridgeJiraIssueParent).filter(
                    or_(
                        BridgeJiraIssueParent.child_issue_key.in_(candidate_keys),
                        BridgeJiraIssueParent.parent_issue_key.in_(candidate_keys),
                    )
                ).update(
                    {BridgeJiraIssueParent.source_present: False},
                    synchronize_session=False,
                )

            for record in records:
                ticket = record["ticket"]
                session.merge(ticket)
                # Hierarchy loading must not delete historical sprint facts;
                # it only adds the current relation discovered in the payload.
                for sprint_row in record.get("sprints", []):
                    sprint = sprint_row["sprint"]
                    if sprint.sprint_completed_at is None:
                        existing_sprint = session.get(DimSprint, sprint.sprint_id)
                        if existing_sprint is not None:
                            sprint.sprint_completed_at = (
                                existing_sprint.sprint_completed_at
                            )
                    session.merge(sprint)
                    session.merge(sprint_row["relation"])

            for edge in edges:
                session.merge(edge)

            session.commit()
            return len(absent_keys)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _source_reconciliation_keys(
        session,
        projects: list[str],
        current_epic_keys: set[str],
        include_all_epics: bool = True,
    ) -> set[str]:
        """Find previously observed hierarchy rows without marking all tickets."""
        old_epic_keys = set()
        if include_all_epics:
            old_epic_keys = {
                row[0]
                for row in session.query(DimTicketJira.issue_key).filter(
                    DimTicketJira.project_key.in_(projects),
                    DimTicketJira.issue_type_name.ilike("epic"),
                ).all()
            }
        connected_keys = set(old_epic_keys) | set(current_epic_keys)
        existing_edges = session.query(BridgeJiraIssueParent).all()

        # Close over the existing bridge so subtasks are included when their
        # parent ticket disappears from the current Jira response.
        changed = True
        while changed:
            changed = False
            for edge in existing_edges:
                if (
                    edge.child_issue_key in connected_keys
                    or edge.parent_issue_key in connected_keys
                ):
                    before = len(connected_keys)
                    connected_keys.update((edge.child_issue_key, edge.parent_issue_key))
                    changed = changed or len(connected_keys) != before
        return connected_keys

    @staticmethod
    def _store_record(records: dict[str, dict[str, Any]], record: dict | None) -> None:
        if record is None:
            return
        issue_key = record["ticket"].issue_key
        existing = records.get(issue_key)
        if existing is None:
            records[issue_key] = record
            return
        # Keep the richest payload when an issue is returned by both the
        # modern parent query and the legacy Epic Link fallback.
        if len(record.get("sprints", [])) > len(existing.get("sprints", [])):
            records[issue_key] = record

    @staticmethod
    def _edge(child_key: str, parent_key: str, relationship_type: str):
        return BridgeJiraIssueParent(
            child_issue_key=child_key,
            parent_issue_key=parent_key,
            relationship_type=relationship_type,
            source_present=True,
            last_seen_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _normalize_projects(projects: Iterable[str] | None) -> list[str]:
        values = [str(project).strip().upper() for project in (projects or DEFAULT_PROJECTS)]
        values = list(dict.fromkeys(value for value in values if value))
        if not values:
            raise ValueError("Informe ao menos um projeto Jira")
        return values

    @staticmethod
    def _quote(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _field_expression(field_name: str) -> str:
        if field_name.startswith("customfield_") or field_name.startswith("cf["):
            return field_name
        escaped = field_name.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    @staticmethod
    def _status_code(exc: requests.HTTPError) -> int | None:
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None)
