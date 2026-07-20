"""Schema changes for Jira crossing status and auditable Clockify links."""

from sqlalchemy import Engine, text


PHASE5_VERSION = 5


def ensure_phase5_schema(engine: Engine) -> None:
    """Add the durable crossing flag and classify existing issue links."""
    with engine.begin() as connection:
        connection.execute(text(
            """
            ALTER TABLE dim_ticket_jira
            ADD COLUMN IF NOT EXISTS atravessamento_flag BOOLEAN
            """
        ))
        connection.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_dim_ticket_jira_atravessamento_flag
            ON dim_ticket_jira (atravessamento_flag)
            """
        ))

        # Reclassify links created by previous versions. Links whose current
        # text no longer exposes a Jira key remain auditable as legacy.
        connection.execute(text(
            r"""
            UPDATE bridge_clockify_entry_issue AS b
            SET extraction_method = CASE
                WHEN e.description ~* '\m[A-Z][A-Z0-9]+-[0-9]+\M'
                 AND e.task_name ~* '\m[A-Z][A-Z0-9]+-[0-9]+\M'
                    THEN 'description_and_task'
                WHEN e.description ~* '\m[A-Z][A-Z0-9]+-[0-9]+\M'
                    THEN 'description'
                WHEN e.task_name ~* '\m[A-Z][A-Z0-9]+-[0-9]+\M'
                    THEN 'task_name'
                ELSE 'legacy'
            END
            FROM fato_clockify_entry AS e
            WHERE e.entry_id = b.entry_id
              AND b.extraction_method IN ('description_or_task', 'legacy_bridge')
            """
        ))

        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE5_VERSION},
        )
