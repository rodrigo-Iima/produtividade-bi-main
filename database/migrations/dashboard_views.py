"""Apply the SQL dashboard view layers in dependency order."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine


MIGRATIONS_DIR = Path(__file__).resolve().parent
DASHBOARD_SQL_FILES = (
    MIGRATIONS_DIR / "phase7_dashboard_gestao_a_vista.sql",
    MIGRATIONS_DIR / "phase9_dashboard_final.sql",
)


def ensure_dashboard_views(engine: Engine) -> None:
    """Recreate the base and final dashboard views in one transaction."""
    statements = [
        _transaction_body(path.read_text(encoding="utf-8"))
        for path in DASHBOARD_SQL_FILES
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)


def _transaction_body(sql: str) -> str:
    """Remove transaction control owned by the SQLAlchemy context."""
    lines = [
        line
        for line in sql.splitlines()
        if line.strip().upper() not in {"BEGIN;", "COMMIT;"}
    ]
    return "\n".join(lines).strip()
