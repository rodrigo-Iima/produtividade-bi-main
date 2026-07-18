"""Enrich ticket/sprint relationships with sprint-entry planning data."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Optional

from database.connection import SessionLocal
from models.dim_sprint import DimSprint
from models.dim_ticket_jira import DimTicketJira
from models.fato_jira_ticket_sprint import FatoJiraTicketSprint
from models.jira_sprint_changelog import JiraSprintChangelog


def compute_sprint_entrada_at(
    created_at: datetime,
    sprint_id: int,
    changelog_entries: list[JiraSprintChangelog],
) -> datetime:
    matching_dates = [
        entry.changed_at
        for entry in changelog_entries
        if entry.change_type == "added" and sprint_matches(entry, sprint_id)
    ]
    return min(matching_dates) if matching_dates else created_at


def compute_planejado_no_inicio(
    sprint_entrada_at: Optional[datetime],
    sprint_start: Optional[datetime],
) -> Optional[bool]:
    if sprint_entrada_at is None or sprint_start is None:
        return None
    return sprint_entrada_at <= sprint_start


def sprint_matches(entry: JiraSprintChangelog, sprint_id: int) -> bool:
    return entry.sprint_id is not None and entry.sprint_id == sprint_id


class SprintEnrichmentService:
    def run(self) -> int:
        session = SessionLocal()
        try:
            rows = session.query(FatoJiraTicketSprint).all()
            if not rows:
                return 0

            issue_keys = {row.issue_key for row in rows}
            changelog_rows = session.query(JiraSprintChangelog).filter(
                JiraSprintChangelog.issue_key.in_(issue_keys),
                JiraSprintChangelog.processing_status == "processed",
            ).all()
            changelog_by_issue: dict[str, list[JiraSprintChangelog]] = defaultdict(list)
            for entry in changelog_rows:
                changelog_by_issue[entry.issue_key].append(entry)

            updated = 0
            for row in rows:
                ticket = session.get(DimTicketJira, row.issue_key)
                sprint = session.get(DimSprint, row.sprint_id)
                if ticket is None or sprint is None:
                    continue

                entrada = compute_sprint_entrada_at(
                    ticket.created_at,
                    row.sprint_id,
                    changelog_by_issue.get(row.issue_key, []),
                )
                planejado = compute_planejado_no_inicio(entrada, sprint.sprint_start)
                if row.sprint_entrada_at != entrada or row.planejado_no_inicio != planejado:
                    row.sprint_entrada_at = entrada
                    row.planejado_no_inicio = planejado
                    updated += 1

            session.commit()
            print(f"[SprintEnrichment] Updated {updated} ticket/sprint relationships")
            return updated
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def run_sprint_enrichment() -> int:
    return SprintEnrichmentService().run()
