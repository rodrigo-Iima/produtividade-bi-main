from datetime import datetime, timezone
import re
from typing import Optional

from clients.jira_client import JiraClient
from config.settings import JIRA_SQUAD_FIELD, JIRA_SPRINT_FIELD
from database.connection import SessionLocal
from models.dim_sprint import DimSprint
from models.dim_ticket_jira import DimTicketJira
from models.fato_jira_ticket_sprint import FatoJiraTicketSprint
from models.jira_sprint_changelog import JiraSprintChangelog
from models.bridge_clockify_entry_sprint import BridgeClockifyEntrySprint
from models.bridge_clockify_entry_issue import BridgeClockifyEntryIssue
from etl.sprint_scope import sprint_is_in_scope


EXCLUDED_SQUADS = {"SWAT"}


class JiraService:
    """Extract Jira tickets and load normalized ticket/sprint tables."""

    FIELDS = [
        "summary",
        "status",
        "project",
        "created",
        "updated",
        "resolutiondate",
        JIRA_SQUAD_FIELD,
        JIRA_SPRINT_FIELD,
    ]

    def __init__(self):
        self.client = JiraClient()

    def run(self, projects: list[str] | None = None, incremental: bool = True):
        if projects is None:
            projects = ["ZGT", "ZG", "ZGTN", "SRE"]

        print(f"\n{'=' * 50}")
        print(f"[JiraETL] Starting extraction for projects {projects}")
        print(f"{'=' * 50}")

        jql = self._build_jql(projects, incremental)
        raw_issues = self.client.search(jql=jql, fields=self.FIELDS)
        if not raw_issues:
            print("[JiraETL] No new/updated issues found.")
            self._purge_out_of_scope_sprints()
            return {
                "extracted": 0,
                "transformed": 0,
                "loaded": 0,
                "issue_keys": [],
            }

        transformed = []
        excluded_issue_keys = []
        skipped = 0
        for issue in raw_issues:
            record = self._transform_issue(issue)
            if record is None:
                if issue.get("key"):
                    excluded_issue_keys.append(issue["key"])
                skipped += 1
            else:
                transformed.append(record)

        if skipped:
            print(f"[JiraETL] Skipped {skipped} tickets from excluded squads")

        loaded = self._load(transformed, excluded_issue_keys)
        print(f"[JiraETL] Loaded {len(transformed)} normalized tickets")
        return {
            "extracted": len(raw_issues),
            "transformed": len(transformed),
            "loaded": loaded,
            "skipped": skipped,
            "issue_keys": [record["ticket"].issue_key for record in transformed],
        }

    def _build_jql(self, projects: list[str], incremental: bool) -> str:
        project_clause = " OR ".join(f"project = {project}" for project in projects)
        parts = [f"({project_clause})", 'created >= "2026-01-01"']

        if incremental:
            last_updated = self._get_last_updated()
            if last_updated:
                jql_date = last_updated.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
                parts.append(f'updated >= "{jql_date}"')
                print(f"[JiraETL] Incremental mode: since {jql_date}")
            else:
                print("[JiraETL] First run — full extraction from 2026-01-01")

        return " AND ".join(parts) + " ORDER BY updated ASC"

    def _get_last_updated(self) -> Optional[datetime]:
        session = SessionLocal()
        try:
            row = session.query(DimTicketJira.updated_at).order_by(
                DimTicketJira.updated_at.desc()
            ).first()
            return row[0] if row else None
        finally:
            session.close()

    def _transform_issue(self, issue: dict) -> Optional[dict]:
        fields = issue["fields"]
        squad_field = fields.get(JIRA_SQUAD_FIELD)
        squad_jira = squad_field.get("value") if isinstance(squad_field, dict) else None
        if squad_jira in EXCLUDED_SQUADS:
            return None

        ticket = DimTicketJira(
            issue_key=issue["key"],
            summary=fields["summary"],
            status_original=fields["status"]["name"],
            project_key=fields["project"]["key"],
            project_name=fields["project"]["name"],
            squad_jira=squad_jira,
            created_at=self._parse_date(fields["created"]),
            resolved_at=self._parse_date(fields.get("resolutiondate")),
            updated_at=self._parse_date(fields["updated"]),
        )

        sprint_rows = []
        for sprint in self._normalize_sprints(fields.get(JIRA_SPRINT_FIELD)):
            sprint_id = sprint.get("id")
            if sprint_id is None:
                continue
            sprint_id = int(sprint_id)
            sprint_start = self._parse_date(sprint.get("startDate"))
            sprint_state = sprint.get("state")
            if not sprint_is_in_scope(sprint_start, sprint_state):
                continue
            sprint_rows.append({
                "sprint": DimSprint(
                    sprint_id=sprint_id,
                    sprint_name=sprint.get("name") or f"Sprint {sprint_id}",
                    sprint_start=sprint_start,
                    sprint_end=self._parse_date(sprint.get("endDate")),
                    sprint_state=sprint_state,
                ),
                "relation": FatoJiraTicketSprint(
                    issue_key=ticket.issue_key,
                    sprint_id=sprint_id,
                    sprint_entrada_at=None,
                    planejado_no_inicio=None,
                ),
            })

        return {"ticket": ticket, "sprints": sprint_rows}

    def _load(self, records: list[dict], excluded_issue_keys: list[str] | None = None) -> int:
        session = SessionLocal()
        try:
            self._delete_excluded_tickets(session, excluded_issue_keys or [])
            for record in records:
                ticket: DimTicketJira = record["ticket"]
                session.merge(ticket)

                issue_key = ticket.issue_key
                session.query(FatoJiraTicketSprint).filter(
                    FatoJiraTicketSprint.issue_key == issue_key
                ).delete(synchronize_session=False)

                for sprint_row in record["sprints"]:
                    session.merge(sprint_row["sprint"])
                    session.merge(sprint_row["relation"])

            self._purge_out_of_scope_sprints(session)
            session.commit()
            return len(records)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _delete_excluded_tickets(session, issue_keys: list[str]) -> int:
        """Remove tickets that became excluded, including dependent bridges."""
        if not issue_keys:
            return 0
        session.query(BridgeClockifyEntryIssue).filter(
            BridgeClockifyEntryIssue.issue_key.in_(issue_keys)
        ).delete(synchronize_session=False)
        session.query(JiraSprintChangelog).filter(
            JiraSprintChangelog.issue_key.in_(issue_keys)
        ).delete(synchronize_session=False)
        session.query(FatoJiraTicketSprint).filter(
            FatoJiraTicketSprint.issue_key.in_(issue_keys)
        ).delete(synchronize_session=False)
        deleted = session.query(DimTicketJira).filter(
            DimTicketJira.issue_key.in_(issue_keys)
        ).delete(synchronize_session=False)
        if deleted:
            print(f"[JiraETL] Removed {deleted} tickets outside the configured scope")
        return deleted

    @staticmethod
    def _purge_out_of_scope_sprints(session=None) -> int:
        owns_session = session is None
        if owns_session:
            session = SessionLocal()

        try:
            now = datetime.now(timezone.utc)
            removed_unresolved_changelog = session.query(JiraSprintChangelog).filter(
                JiraSprintChangelog.processing_status == "processed",
                JiraSprintChangelog.sprint_id.is_(None),
            ).delete(synchronize_session=False)
            out_of_scope_ids = [
                sprint.sprint_id
                for sprint in session.query(DimSprint).all()
                if not sprint_is_in_scope(
                    sprint.sprint_start,
                    sprint.sprint_state,
                    now=now,
                )
            ]
            if not out_of_scope_ids:
                if owns_session:
                    session.commit()
                if removed_unresolved_changelog:
                    print(
                        f"[JiraETL] Removed {removed_unresolved_changelog} "
                        "processed changelog rows without a sprint"
                    )
                return 0

            session.query(JiraSprintChangelog).filter(
                JiraSprintChangelog.sprint_id.in_(out_of_scope_ids)
            ).delete(synchronize_session=False)
            session.query(FatoJiraTicketSprint).filter(
                FatoJiraTicketSprint.sprint_id.in_(out_of_scope_ids)
            ).delete(synchronize_session=False)
            session.query(BridgeClockifyEntrySprint).filter(
                BridgeClockifyEntrySprint.sprint_id.in_(out_of_scope_ids)
            ).update(
                {
                    BridgeClockifyEntrySprint.sprint_id: None,
                    BridgeClockifyEntrySprint.assignment_status: "sem_sprint",
                    BridgeClockifyEntrySprint.assignment_reason: "sprint_out_of_scope",
                },
                synchronize_session=False,
            )
            deleted = session.query(DimSprint).filter(
                DimSprint.sprint_id.in_(out_of_scope_ids)
            ).delete(synchronize_session=False)

            if owns_session:
                session.commit()
            print(
                f"[JiraETL] Removed {deleted} sprints outside the configured scope "
                f"and {removed_unresolved_changelog} unresolved changelog rows"
            )
            return deleted
        except Exception:
            if owns_session:
                session.rollback()
            raise
        finally:
            if owns_session:
                session.close()

    @staticmethod
    def _normalize_sprints(value) -> list[dict]:
        if isinstance(value, list):
            return value
        return []

    @staticmethod
    def _parse_date(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        elif re.search(r"[+-]\d{4}$", normalized):
            normalized = normalized[:-5] + normalized[-5:-2] + ":" + normalized[-2:]

        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
