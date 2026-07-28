"""Explicit schema migration entrypoint for containerized environments."""

from __future__ import annotations

from collections.abc import Callable


def run_migrations(
    migration_operation: Callable[[], None] | None = None,
    dispose_operation: Callable[[], None] | None = None,
) -> int:
    """Apply the schema once and always release database connections."""
    if migration_operation is None:
        from database.schema import ensure_portable_schema

        migration_operation = ensure_portable_schema

    if dispose_operation is None:
        from database.connection import engine

        dispose_operation = engine.dispose

    try:
        migration_operation()
        print("[Migration] Schema atualizado com sucesso")
        return 0
    except Exception as exc:
        print(f"[Migration] Falha ao atualizar o schema: {exc}")
        return 1
    finally:
        dispose_operation()
