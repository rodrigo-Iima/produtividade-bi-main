"""Remove compatibility objects after the canonical dashboard cutover."""

from sqlalchemy import Engine, text


PHASE27_VERSION = 27

DEPRECATED_VIEWS = (
    "vw_dashboard_entry_base",
    "vw_jira_ticket_sprint_detail",
    "vw_clockify_entry_detail",
    "vw_clockify_entry_tag_detail",
    "vw_clockify_entry_sprint_detail",
    "vw_clockify_entry_issue_detail",
)

DEPRECATED_TABLES = (
    "dim_calendario",
    "fato_sprint_capacidade",
    "etl_view_version",
)


def ensure_phase27_schema(engine: Engine) -> None:
    """Drop deprecated objects without cascading into unknown consumers."""
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '30s'"))
        connection.execute(text("SET LOCAL statement_timeout = '5min'"))

        for view_name in DEPRECATED_VIEWS:
            connection.execute(
                text(f'DROP VIEW IF EXISTS public."{view_name}"')
            )
        for table_name in DEPRECATED_TABLES:
            connection.execute(
                text(f'DROP TABLE IF EXISTS public."{table_name}"')
            )

        connection.execute(
            text(
                "INSERT INTO public.etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE27_VERSION},
        )
