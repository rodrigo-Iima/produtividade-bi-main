"""Store the final historical planning classification per ticket and sprint."""

from sqlalchemy import Engine, text


PHASE12_VERSION = 12


def ensure_phase12_schema(engine: Engine) -> None:
    """Add the relationship-level planning status and its audit source."""
    with engine.begin() as connection:
        connection.execute(text(
            """
            ALTER TABLE public.fato_jira_ticket_sprint
            ADD COLUMN IF NOT EXISTS planejamento_status VARCHAR(30),
            ADD COLUMN IF NOT EXISTS planejamento_source VARCHAR(50)
            """
        ))
        connection.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_fato_jira_ticket_sprint_planejamento_status
                ON public.fato_jira_ticket_sprint (planejamento_status)
            """
        ))
        connection.execute(text(
            """
            UPDATE public.fato_jira_ticket_sprint
            SET planejamento_status = CASE
                    WHEN planejado_no_inicio IS TRUE THEN 'planejado'
                    WHEN planejado_no_inicio IS FALSE THEN 'atravessado'
                    ELSE 'sem_classificacao'
                END,
                planejamento_source = CASE
                    WHEN planejado_no_inicio IS NULL THEN 'sem_dados'
                    ELSE 'historico_changelog'
                END
            WHERE planejamento_status IS NULL
            """
        ))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE12_VERSION},
        )
