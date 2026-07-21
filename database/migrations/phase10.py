"""Allow board-level Sprint × Squad mappings without a quick filter."""

from sqlalchemy import Engine, text


PHASE10_VERSION = 10


def ensure_phase10_schema(engine: Engine) -> None:
    """Make the quick-filter reference optional for single-Squad boards."""
    with engine.begin() as connection:
        connection.execute(text(
            """
            ALTER TABLE public.bridge_sprint_squad
            ALTER COLUMN quick_filter_id DROP NOT NULL
            """
        ))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE10_VERSION},
        )
