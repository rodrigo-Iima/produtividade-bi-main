"""Operational status and database health queries."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from database.connection import engine


REQUIRED_TABLES = (
    "etl_run_log",
    "dim_sprint",
    "dim_ticket_jira",
    "fato_clockify_entry",
)


def get_status(limit: int = 10) -> dict[str, Any]:
    """Return recent pipeline runs and steps from the audit table."""
    if limit < 1:
        raise ValueError("limit deve ser maior ou igual a um")

    with engine.connect() as connection:
        pipeline_rows = connection.execute(text(
            """
            SELECT run_id, status, started_at, finished_at, error_message
            FROM etl_run_log
            WHERE step_name = 'pipeline'
            ORDER BY started_at DESC
            LIMIT :limit
            """
        ), {"limit": limit}).mappings().all()

        latest_run_id = pipeline_rows[0]["run_id"] if pipeline_rows else None
        step_rows = []
        if latest_run_id:
            step_rows = connection.execute(text(
                """
                SELECT step_name, status, started_at, finished_at,
                       records_extracted, records_transformed, records_loaded,
                       error_message
                FROM etl_run_log
                WHERE run_id = :run_id
                ORDER BY started_at
                """
            ), {"run_id": latest_run_id}).mappings().all()

    return {
        "latest_run": _serialize(dict(pipeline_rows[0])) if pipeline_rows else None,
        "recent_runs": [_serialize(dict(row)) for row in pipeline_rows],
        "latest_steps": [_serialize(dict(row)) for row in step_rows],
    }


def healthcheck() -> dict[str, Any]:
    """Check database connectivity and presence of the operational model."""
    checks: dict[str, Any] = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            checks["database_connection"] = True
            rows = connection.execute(text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = ANY(:table_names)
                """
            ), {"table_names": list(REQUIRED_TABLES)}).scalars().all()
            found = set(rows)
            checks["required_tables"] = {
                table: table in found for table in REQUIRED_TABLES
            }
    except Exception as exc:
        checks["database_connection"] = False
        checks["error"] = str(exc)

    checks["healthy"] = bool(
        checks.get("database_connection")
        and all(checks.get("required_tables", {}).values())
    )
    return checks


def _serialize(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
