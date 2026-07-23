"""Create the collaborator × Sprint theoretical capacity fact."""

from sqlalchemy import Engine, text


PHASE14_VERSION = 14


def ensure_phase14_schema(engine: Engine) -> None:
    """Create the idempotent Sprint capacity fact and supporting indexes."""
    with engine.begin() as connection:
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.fato_sprint_capacidade (
                sprint_id INTEGER NOT NULL
                    REFERENCES public.dim_sprint(sprint_id) ON DELETE CASCADE,
                user_id VARCHAR(100) NOT NULL
                    REFERENCES public.dim_colaborador(user_id) ON DELETE CASCADE,
                squad_id INTEGER NOT NULL
                    REFERENCES public.dim_squad(squad_id),
                squad_name VARCHAR(200) NOT NULL,
                papel VARCHAR(100),
                capacity_group_id VARCHAR(100) NOT NULL
                    REFERENCES public.dim_clockify_group(group_id),
                capacity_group_name VARCHAR(200) NOT NULL,
                capacity_hours_week NUMERIC(5, 2) NOT NULL,
                sprint_start TIMESTAMPTZ NOT NULL,
                sprint_end TIMESTAMPTZ NOT NULL,
                business_days INTEGER NOT NULL,
                capacity_hours NUMERIC(8, 2) NOT NULL,
                source VARCHAR(50) NOT NULL DEFAULT 'clockify_current_configuration',
                calculated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (sprint_id, user_id),
                CONSTRAINT ck_fato_sprint_capacity_week
                    CHECK (capacity_hours_week > 0),
                CONSTRAINT ck_fato_sprint_capacity_days
                    CHECK (business_days >= 0),
                CONSTRAINT ck_fato_sprint_capacity_hours
                    CHECK (capacity_hours >= 0),
                CONSTRAINT ck_fato_sprint_capacity_window
                    CHECK (sprint_end > sprint_start)
            )
            """
        ))

        connection.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_fato_sprint_capacity_sprint
                ON public.fato_sprint_capacidade (sprint_id);
            CREATE INDEX IF NOT EXISTS ix_fato_sprint_capacity_squad
                ON public.fato_sprint_capacidade (squad_id);
            CREATE INDEX IF NOT EXISTS ix_fato_sprint_capacity_group
                ON public.fato_sprint_capacidade (capacity_group_id);
            CREATE INDEX IF NOT EXISTS ix_fato_sprint_capacity_source
                ON public.fato_sprint_capacidade (source);
            """
        ))

        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE14_VERSION},
        )
