"""Operational tables for the Phase 4 transformation/load pipeline."""

from sqlalchemy import Engine, text


PHASE4_VERSION = 4


def ensure_phase4_schema(engine: Engine) -> None:
    """Create the ETL execution audit table and record schema version 4."""
    with engine.begin() as connection:
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS etl_run_log (
                run_id VARCHAR(36) NOT NULL,
                step_name VARCHAR(100) NOT NULL,
                status VARCHAR(20) NOT NULL,
                started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMPTZ,
                records_extracted INTEGER NOT NULL DEFAULT 0,
                records_transformed INTEGER NOT NULL DEFAULT 0,
                records_loaded INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                PRIMARY KEY (run_id, step_name)
            )
            """
        ))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE4_VERSION},
        )
