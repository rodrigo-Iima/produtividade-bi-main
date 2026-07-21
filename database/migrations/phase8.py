"""Historical Clockify classification fields for dashboard foundations."""

from sqlalchemy import Engine, text


PHASE8_VERSION = 8


def ensure_phase8_schema(engine: Engine) -> None:
    """Add immutable-at-load Clockify classification snapshots."""
    with engine.begin() as connection:
        connection.execute(text(
            """
            ALTER TABLE public.fato_clockify_entry
            ADD COLUMN IF NOT EXISTS squad_id_at_entry INTEGER
                REFERENCES public.dim_squad(squad_id),
            ADD COLUMN IF NOT EXISTS squad_name_at_entry VARCHAR(200),
            ADD COLUMN IF NOT EXISTS papel_at_entry VARCHAR(100),
            ADD COLUMN IF NOT EXISTS entry_date_local DATE
            """
        ))

        # Do not infer historical Squad/Papel from the current collaborator
        # dimension. A complete Clockify reload must populate these snapshots.
        connection.execute(text(
            """
            UPDATE public.fato_clockify_entry
            SET entry_date_local = (
                started_at AT TIME ZONE 'America/Sao_Paulo'
            )::date
            WHERE started_at IS NOT NULL
              AND entry_date_local IS NULL
            """
        ))

        connection.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_fato_clockify_entry_entry_date_local
                ON public.fato_clockify_entry (entry_date_local)
            """
        ))
        connection.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_fato_clockify_entry_squad_at_entry
                ON public.fato_clockify_entry (squad_id_at_entry)
            """
        ))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE8_VERSION},
        )
