"""Store Jira's real Sprint completion timestamp separately from its plan."""

from sqlalchemy import Engine, text


PHASE23_VERSION = 23


def ensure_phase23_schema(engine: Engine) -> None:
    """Add the completion timestamp used by real Sprint activity windows."""
    with engine.begin() as connection:
        # Adding a column requires a table lock. Fail fast during deployment
        # instead of waiting indefinitely behind an ETL or dashboard session.
        connection.execute(text("SET LOCAL lock_timeout = '30s'"))
        connection.execute(text("SET LOCAL statement_timeout = '5min'"))
        connection.execute(
            text(
                "ALTER TABLE public.dim_sprint "
                "ADD COLUMN IF NOT EXISTS sprint_completed_at TIMESTAMPTZ"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_dim_sprint_completed_at "
                "ON public.dim_sprint (sprint_completed_at)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE23_VERSION},
        )
