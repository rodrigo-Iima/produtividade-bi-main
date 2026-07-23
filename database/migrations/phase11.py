"""Persist Jira's native issue type for sprint analytics."""

from sqlalchemy import Engine, text


PHASE11_VERSION = 11


def ensure_phase11_schema(engine: Engine) -> None:
    """Add the native Jira issue type to the ticket dimension."""
    with engine.begin() as connection:
        connection.execute(text(
            """
            ALTER TABLE public.dim_ticket_jira
            ADD COLUMN IF NOT EXISTS issue_type_id VARCHAR(30),
            ADD COLUMN IF NOT EXISTS issue_type_name VARCHAR(100)
            """
        ))
        connection.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_dim_ticket_jira_issue_type_name
                ON public.dim_ticket_jira (issue_type_name)
            """
        ))
        connection.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_dim_ticket_jira_issue_type_id
                ON public.dim_ticket_jira (issue_type_id)
            """
        ))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE11_VERSION},
        )
