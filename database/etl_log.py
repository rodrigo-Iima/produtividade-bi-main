"""Small PostgreSQL-backed audit logger for ETL transformation/load steps."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from database.connection import engine


class EtlRunLogger:
    """Persist one status row per pipeline step without sharing ETL sessions."""

    def __init__(self, run_id: str):
        self.run_id = run_id

    def start(self, step_name: str) -> None:
        self._execute(
            """
            INSERT INTO etl_run_log(run_id, step_name, status, started_at)
            VALUES (:run_id, :step_name, 'running', :started_at)
            ON CONFLICT (run_id, step_name) DO UPDATE SET
                status = 'running',
                started_at = EXCLUDED.started_at,
                finished_at = NULL,
                error_message = NULL
            """,
            {
                "run_id": self.run_id,
                "step_name": step_name,
                "started_at": datetime.now(timezone.utc),
            },
        )

    def finish(self, step_name: str, result: Any = None) -> None:
        counts = _result_counts(result)
        self._execute(
            """
            UPDATE etl_run_log
            SET status = 'success',
                finished_at = :finished_at,
                records_extracted = :records_extracted,
                records_transformed = :records_transformed,
                records_loaded = :records_loaded,
                error_message = NULL
            WHERE run_id = :run_id AND step_name = :step_name
            """,
            {
                "run_id": self.run_id,
                "step_name": step_name,
                "finished_at": datetime.now(timezone.utc),
                **counts,
            },
        )

    def fail(self, step_name: str, error: Exception) -> None:
        self._execute(
            """
            UPDATE etl_run_log
            SET status = 'failed',
                finished_at = :finished_at,
                error_message = :error_message
            WHERE run_id = :run_id AND step_name = :step_name
            """,
            {
                "run_id": self.run_id,
                "step_name": step_name,
                "finished_at": datetime.now(timezone.utc),
                "error_message": str(error)[:4000],
            },
        )

    def _execute(self, statement: str, parameters: dict[str, Any]) -> None:
        with engine.begin() as connection:
            connection.execute(text(statement), parameters)


def _result_counts(result: Any) -> dict[str, int]:
    if isinstance(result, dict):
        return {
            "records_extracted": int(result.get("extracted", 0) or 0),
            "records_transformed": int(result.get("transformed", 0) or 0),
            "records_loaded": int(result.get("loaded", 0) or 0),
        }
    if isinstance(result, int):
        return {
            "records_extracted": 0,
            "records_transformed": 0,
            "records_loaded": result,
        }
    return {
        "records_extracted": 0,
        "records_transformed": 0,
        "records_loaded": 0,
    }
