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
