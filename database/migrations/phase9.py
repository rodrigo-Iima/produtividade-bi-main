"""Jira board quick filters and shared Sprint × Squad mappings."""

from sqlalchemy import Engine, text


PHASE9_VERSION = 9


def ensure_phase9_schema(engine: Engine) -> None:
    """Create the durable source tables for the shared-sprint model."""
    with engine.begin() as connection:
        connection.execute(text(
            """
            ALTER TABLE public.dim_sprint
            ADD COLUMN IF NOT EXISTS origin_board_id BIGINT
            """
        ))
        connection.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_dim_sprint_origin_board_id
                ON public.dim_sprint (origin_board_id)
            """
        ))
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.dim_jira_board (
                board_id BIGINT PRIMARY KEY,
                board_name VARCHAR(200)
            )
            """
        ))
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.dim_jira_quick_filter (
                board_id BIGINT NOT NULL
                    REFERENCES public.dim_jira_board(board_id)
                    ON DELETE CASCADE,
                quick_filter_id BIGINT NOT NULL,
                name VARCHAR(200) NOT NULL,
                jql TEXT NOT NULL,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (board_id, quick_filter_id)
            )
            """
        ))
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS public.bridge_sprint_squad (
                sprint_id INTEGER NOT NULL
                    REFERENCES public.dim_sprint(sprint_id)
                    ON DELETE CASCADE,
                squad_id INTEGER NOT NULL
                    REFERENCES public.dim_squad(squad_id),
                board_id BIGINT NOT NULL,
                quick_filter_id BIGINT,
                mapping_source VARCHAR(50) NOT NULL,
                mapped_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (sprint_id, squad_id),
                FOREIGN KEY (board_id, quick_filter_id)
                    REFERENCES public.dim_jira_quick_filter(
                        board_id, quick_filter_id
                    )
                    ON DELETE CASCADE
            )
            """
        ))
        connection.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_bridge_sprint_squad_squad_id
                ON public.bridge_sprint_squad (squad_id)
            """
        ))
        connection.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_bridge_sprint_squad_filter
                ON public.bridge_sprint_squad (board_id, quick_filter_id)
            """
        ))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE9_VERSION},
        )
