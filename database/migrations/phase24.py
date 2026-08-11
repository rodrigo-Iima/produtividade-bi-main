"""Persist Jira original estimates in their canonical source unit."""

from sqlalchemy import Engine, text


PHASE24_VERSION = 24


def ensure_phase24_schema(engine: Engine) -> None:
    """Add the nullable Jira estimate column used by ticket views.

    Jira's REST API reports the original estimate in seconds. Keeping seconds
    in the dimension preserves the API value; dashboard views expose derived
    hours for aggregation alongside Clockify and Flow measures.
    """
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '30s'"))
        connection.execute(text("SET LOCAL statement_timeout = '5min'"))
        connection.execute(
            text(
                "ALTER TABLE public.dim_ticket_jira "
                "ADD COLUMN IF NOT EXISTS original_estimate_seconds BIGINT"
            )
        )
        connection.execute(
            text(
                "COMMENT ON COLUMN public.dim_ticket_jira.original_estimate_seconds "
                "IS 'Jira timetracking.originalEstimateSeconds; NULL means no estimate.'"
            )
        )
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE24_VERSION},
        )
