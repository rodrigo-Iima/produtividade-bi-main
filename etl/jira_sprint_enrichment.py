"""Enrich ticket/sprint relationships with sprint-entry planning data."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from database.connection import SessionLocal
from models.dim_sprint import DimSprint
from models.dim_ticket_jira import DimTicketJira
from models.fato_jira_ticket_sprint import FatoJiraTicketSprint
from models.jira_sprint_changelog import JiraSprintChangelog


PLANNING_RULE_START = datetime(2026, 5, 1, tzinfo=timezone.utc)
PLANNING_STATUS_PLANNED = "planejado"
PLANNING_STATUS_CROSSED = "atravessado"
PLANNING_STATUS_OUT_OF_WINDOW = "fora_da_janela"
PLANNING_STATUS_UNCLASSIFIED = "sem_classificacao"


def compute_sprint_entrada_at(
    created_at: Optional[datetime],
    sprint_id: int,
    changelog_entries: list[JiraSprintChangelog],
) -> Optional[datetime]:
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


def compute_planejamento_status(
    sprint_start: Optional[datetime],
    sprint_end: Optional[datetime],
    sprint_entrada_at: Optional[datetime],
    planejado_no_inicio: Optional[bool],
    *,
    carregamento_sprint_anterior: bool = False,
    rule_start: datetime = PLANNING_RULE_START,
) -> tuple[str, str]:
    """Classify one ticket × Sprint relationship using the business rule.

    Before the Atravessamento field existed, the historical changelog remains
    the compatible source. From 2026-05-01 onward, a ticket carried from a
    previous Sprint is planned even when Jira records its new Sprint entry
    after the Sprint start. Multiple add/remove events in the same Sprint do
    not change ``sprint_entrada_at`` because it is based on the first add.
    """
    start = _as_utc(sprint_start)
    end = _as_utc(sprint_end)
    entry = _as_utc(sprint_entrada_at)
    cutoff = _as_utc(rule_start)

    if start is None:
        return PLANNING_STATUS_UNCLASSIFIED, "sprint_sem_inicio"

    if start < cutoff:
        if planejado_no_inicio is True:
            return PLANNING_STATUS_PLANNED, "historico_changelog"
        if planejado_no_inicio is False:
            return PLANNING_STATUS_CROSSED, "historico_changelog"
        return PLANNING_STATUS_UNCLASSIFIED, "historico_sem_dados"

    if entry is None:
        return PLANNING_STATUS_UNCLASSIFIED, "entrada_sem_data"
    if end is not None and entry > end:
        return PLANNING_STATUS_OUT_OF_WINDOW, "entrada_apos_fim"
    if carregamento_sprint_anterior:
        return PLANNING_STATUS_PLANNED, "carregamento_sprint_anterior"
    if entry <= start:
        return PLANNING_STATUS_PLANNED, "entrada_antes_inicio"
    return PLANNING_STATUS_CROSSED, "entrada_apos_inicio"


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

            relations_by_issue: dict[str, list[dict]] = defaultdict(list)
            for row in rows:
                ticket = session.get(DimTicketJira, row.issue_key)
                sprint = session.get(DimSprint, row.sprint_id)
                if ticket is None or sprint is None:
                    continue

                entries = changelog_by_issue.get(row.issue_key, [])
                entrada = compute_sprint_entrada_at(
                    ticket.created_at,
                    row.sprint_id,
                    entries,
                )
                planejado = compute_planejado_no_inicio(entrada, sprint.sprint_start)
                relations_by_issue[row.issue_key].append({
                    "row": row,
                    "ticket": ticket,
                    "sprint": sprint,
                    "sprint_entrada_at": entrada,
                    "planejado_no_inicio": planejado,
                })

            updated = 0
            status_counts: dict[str, int] = defaultdict(int)
            for relations in relations_by_issue.values():
                relations.sort(
                    key=lambda item: (
                        _as_utc(item["sprint"].sprint_start) or datetime.min.replace(tzinfo=timezone.utc),
                        item["sprint"].sprint_id,
                    )
                )
                for index, relation in enumerate(relations):
                    carried = _is_carried_from_previous_sprint(relations, index)
                    status, source = compute_planejamento_status(
                        relation["sprint"].sprint_start,
                        relation["sprint"].sprint_end,
                        relation["sprint_entrada_at"],
                        relation["planejado_no_inicio"],
                        carregamento_sprint_anterior=carried,
                    )
                    row = relation["row"]
                    if (
                        row.sprint_entrada_at != relation["sprint_entrada_at"]
                        or row.planejado_no_inicio != relation["planejado_no_inicio"]
                        or row.planejamento_status != status
                        or row.planejamento_source != source
                    ):
                        row.sprint_entrada_at = relation["sprint_entrada_at"]
                        row.planejado_no_inicio = relation["planejado_no_inicio"]
                        row.planejamento_status = status
                        row.planejamento_source = source
                        updated += 1
                    status_counts[status] += 1

            session.commit()
            print(
                "[SprintEnrichment] Updated "
                f"{updated} ticket/sprint relationships; "
                f"statuses={dict(sorted(status_counts.items()))}"
            )
            return updated
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def run_sprint_enrichment() -> int:
    return SprintEnrichmentService().run()


def _is_carried_from_previous_sprint(
    relations: list[dict],
    index: int,
) -> bool:
    """Identify a late entry that is the next Sprint for the same ticket."""
    current = relations[index]
    current_sprint = current["sprint"]
    current_start = _as_utc(current_sprint.sprint_start)
    current_end = _as_utc(current_sprint.sprint_end)
    entry = _as_utc(current["sprint_entrada_at"])
    if current_start is None or entry is None or entry <= current_start:
        return False
    if current_end is not None and entry > current_end:
        return False
    if index == 0:
        return False

    previous = relations[index - 1]
    previous_sprint = previous["sprint"]
    previous_start = _as_utc(previous_sprint.sprint_start)
    previous_end = _as_utc(previous_sprint.sprint_end)
    previous_entry = _as_utc(previous["sprint_entrada_at"])
    if previous_start is None or previous_end is None or previous_end > current_start:
        return False
    if previous_entry is not None and previous_entry > previous_end:
        return False

    current_board = current_sprint.origin_board_id
    previous_board = previous_sprint.origin_board_id
    if (
        current_board is not None
        and previous_board is not None
        and current_board != previous_board
    ):
        return False
    return True


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
