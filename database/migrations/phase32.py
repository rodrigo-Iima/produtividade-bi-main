"""Converge the dashboard on the canonical Sprint × Squad window."""

from sqlalchemy import Engine, text

from database.migrations.sprint_window import SPRINT_WINDOW_REPLACE_SQL

PHASE32_VERSION = 32


def ensure_phase32_schema(engine: Engine) -> None:
    """Record convergence on the window contract after dependent views."""
    # The dependency-safe schema order applies SPRINT_WINDOW_VIEW_SQL in
    # phase 25 before rebuilding the entry and capacity contracts. Phase 32
    # is the durable migration marker and intentionally does not drop the
    # canonical view after its dependents have been recreated.
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '30s'"))
        if connection.execute(
            text("SELECT to_regclass('public.vw_dashboard_sprint_window')")
        ).scalar() is None:
            raise RuntimeError(
                "vw_dashboard_sprint_window não foi criada antes da phase32"
            )
        connection.exec_driver_sql(SPRINT_WINDOW_REPLACE_SQL)
        connection.execute(
            text(
                "INSERT INTO public.etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE32_VERSION},
        )
