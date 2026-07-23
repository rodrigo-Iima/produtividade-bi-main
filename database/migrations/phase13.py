"""Persist Clockify groups and current user-group memberships."""

from sqlalchemy import Engine, text


PHASE13_VERSION = 13


def ensure_phase13_schema(engine: Engine) -> None:
    """Create the group catalog and collaborator × group bridge."""
    with engine.begin() as connection:
        connection.execute(text(
            """
            ALTER TABLE public.dim_colaborador
            ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS clockify_last_seen_at TIMESTAMPTZ
            """
        ))

        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.dim_clockify_group (
                group_id VARCHAR(100) PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                group_type VARCHAR(30) NOT NULL,
                capacity_hours_week NUMERIC(5, 2),
                source VARCHAR(30) NOT NULL DEFAULT 'clockify',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_dim_clockify_group_source_name
                    UNIQUE (source, name),
                CONSTRAINT ck_dim_clockify_group_type
                    CHECK (group_type IN ('capacity', 'squad', 'papel', 'other')),
                CONSTRAINT ck_dim_clockify_group_capacity
                    CHECK (capacity_hours_week IS NULL OR capacity_hours_week >= 0)
            )
            """
        ))

        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.bridge_clockify_user_group (
                user_id VARCHAR(100) NOT NULL
                    REFERENCES public.dim_colaborador(user_id) ON DELETE CASCADE,
                group_id VARCHAR(100) NOT NULL
                    REFERENCES public.dim_clockify_group(group_id) ON DELETE CASCADE,
                is_current BOOLEAN NOT NULL DEFAULT TRUE,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, group_id)
            )
            """
        ))

        connection.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_dim_clockify_group_type
                ON public.dim_clockify_group (group_type);
            CREATE INDEX IF NOT EXISTS ix_bridge_clockify_user_group_group
                ON public.bridge_clockify_user_group (group_id);
            CREATE INDEX IF NOT EXISTS ix_bridge_clockify_user_group_current
                ON public.bridge_clockify_user_group (is_current);
            CREATE INDEX IF NOT EXISTS ix_dim_colaborador_active
                ON public.dim_colaborador (is_active);
            """
        ))

        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE13_VERSION},
        )
