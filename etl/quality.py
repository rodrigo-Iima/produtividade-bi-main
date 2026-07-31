"""Post-load data quality checks for the transformed PostgreSQL model."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from database.connection import SessionLocal


class DataQualityError(RuntimeError):
    """Raised when a critical relationship or scope check fails."""

    def __init__(self, checks: dict[str, int]):
        self.checks = checks
        failures = {name: value for name, value in checks.items() if value}
        super().__init__(f"Data quality checks failed: {failures}")


def validate_loaded_data() -> dict[str, Any]:
    """Validate required relationships, sprint scope and duration values."""
    statements = {
        "orphan_clockify_tag_links": """
            SELECT COUNT(*) FROM bridge_clockify_entry_tag b
            LEFT JOIN fato_clockify_entry e ON e.entry_id = b.entry_id
            LEFT JOIN dim_tag t ON t.tag_id = b.tag_id
            WHERE e.entry_id IS NULL OR t.tag_id IS NULL
        """,
        "orphan_clockify_issue_links": """
            SELECT COUNT(*) FROM bridge_clockify_entry_issue b
            LEFT JOIN fato_clockify_entry e ON e.entry_id = b.entry_id
            LEFT JOIN dim_ticket_jira t ON t.issue_key = b.issue_key
            WHERE e.entry_id IS NULL OR t.issue_key IS NULL
        """,
        "orphan_clockify_sprint_links": """
            SELECT COUNT(*) FROM bridge_clockify_entry_sprint b
            LEFT JOIN fato_clockify_entry e ON e.entry_id = b.entry_id
            LEFT JOIN dim_sprint s ON s.sprint_id = b.sprint_id
            WHERE e.entry_id IS NULL OR (b.sprint_id IS NOT NULL AND s.sprint_id IS NULL)
        """,
        "orphan_ticket_sprint_links": """
            SELECT COUNT(*) FROM fato_jira_ticket_sprint r
            LEFT JOIN dim_ticket_jira t ON t.issue_key = r.issue_key
            LEFT JOIN dim_sprint s ON s.sprint_id = r.sprint_id
            WHERE t.issue_key IS NULL OR s.sprint_id IS NULL
        """,
        "invalid_ticket_sprint_planning_status": """
            SELECT COUNT(*)
            FROM fato_jira_ticket_sprint
            WHERE planejamento_status IS NULL
               OR planejamento_status NOT IN (
                'planejado', 'atravessado', 'fora_da_janela', 'sem_classificacao'
            )
        """,
        "orphan_changelog_links": """
            SELECT COUNT(*) FROM jira_sprint_changelog c
            LEFT JOIN dim_ticket_jira t ON t.issue_key = c.issue_key
            LEFT JOIN dim_sprint s ON s.sprint_id = c.sprint_id
            WHERE t.issue_key IS NULL OR (c.sprint_id IS NOT NULL AND s.sprint_id IS NULL)
        """,
        "out_of_scope_sprints": """
            SELECT COUNT(*) FROM dim_sprint
            WHERE sprint_start <= TIMESTAMPTZ '2026-01-01 00:00:00+00'
               OR sprint_start > CURRENT_TIMESTAMP
               OR sprint_state IS NULL
               OR UPPER(sprint_state) NOT IN ('ACTIVE', 'CLOSED')
        """,
        "negative_durations": """
            SELECT COUNT(*) FROM fato_clockify_entry
            WHERE duration_seconds < 0
        """,
        "invalid_clockify_intervals": """
            SELECT COUNT(*) FROM fato_clockify_entry
            WHERE started_at IS NULL OR ended_at IS NULL OR ended_at < started_at
        """,
        "invalid_sprint_assignment_status": """
            SELECT COUNT(*) FROM bridge_clockify_entry_sprint
            WHERE assignment_status NOT IN ('atribuido', 'ambiguo', 'sem_sprint', 'sem_ticket')
        """,
        "invalid_clockify_issue_extraction_method": """
            SELECT COUNT(*) FROM bridge_clockify_entry_issue
            WHERE extraction_method NOT IN (
                'description', 'task_name', 'description_and_task', 'legacy'
            )
        """,
        "orphan_flow_days": """
            SELECT COUNT(*) FROM fato_flow_dia d
            LEFT JOIN dim_flow_pessoa p
              ON p.flow_person_id = d.flow_person_id
            WHERE p.flow_person_id IS NULL
        """,
        "orphan_flow_markings": """
            SELECT COUNT(*) FROM fato_flow_marcacao m
            LEFT JOIN fato_flow_dia d
              ON d.flow_person_id = m.flow_person_id
             AND d.work_date = m.work_date
            WHERE d.flow_person_id IS NULL
        """,
        "invalid_flow_day_periods": """
            SELECT COUNT(*) FROM fato_flow_dia
            WHERE period_start > period_end
               OR work_date NOT BETWEEN period_start AND period_end
        """,
        "invalid_flow_mark_sequences": """
            SELECT COUNT(*)
            FROM (
                SELECT flow_person_id, work_date
                FROM fato_flow_marcacao
                GROUP BY flow_person_id, work_date
                HAVING MIN(order_in_day) <> 1
                    OR MAX(order_in_day) <> COUNT(*)
            ) invalid_sequences
        """,
        "orphan_flow_intervals": """
            SELECT COUNT(*) FROM fato_flow_intervalo i
            LEFT JOIN fato_flow_dia d
              ON d.flow_person_id = i.flow_person_id
             AND d.work_date = i.work_date
            WHERE d.flow_person_id IS NULL
        """,
        "invalid_flow_intervals": """
            SELECT COUNT(*) FROM fato_flow_intervalo
            WHERE ended_at < started_at
               OR duration_seconds < 0
               OR duration_seconds <> ROUND(
                    EXTRACT(EPOCH FROM (ended_at - started_at))
               )
               OR exit_mark_order <> entry_mark_order + 1
        """,
        "invalid_hours_reconciliation": """
            SELECT COUNT(*) FROM fato_conferencia_horas_dia
            WHERE point_mark_count < 0
               OR point_interval_count < 0
               OR point_worked_seconds < 0
               OR clockify_entry_count < 0
               OR clockify_seconds < 0
               OR tolerance_seconds < 0
               OR delta_seconds
                  <> clockify_seconds - point_worked_seconds
               OR within_tolerance
                  <> (
                      point_complete
                      AND clockify_entry_count > 0
                      AND ABS(delta_seconds) <= tolerance_seconds
                  )
        """,
        "dashboard_entries_without_sprint": """
            SELECT COUNT(*)
            FROM public.vw_dashboard_entry_final
            WHERE sprint_assignment_status NOT IN (
                'atribuido', 'nao_aplicavel', 'historico_sem_sprint'
            )
        """,
    }

    counts = {
        name: int(value)
        for name, value in _execute_counts(statements).items()
    }
    if any(counts.values()):
        raise DataQualityError(counts)
    return {"status": "ok", "checks": counts}


def _execute_counts(statements: dict[str, str]) -> dict[str, int]:
    session = SessionLocal()
    try:
        return {
            name: session.execute(text(statement)).scalar_one()
            for name, statement in statements.items()
        }
    finally:
        session.close()
