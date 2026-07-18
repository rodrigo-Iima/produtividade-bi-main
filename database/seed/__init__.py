from sqlalchemy.orm import Session

from .loader import (
    load_dim_squad,
    load_dim_status,
    load_dim_calendario,
    load_dim_tags,
)


def seed_all(session: Session | None = None) -> None:
    """Seed all dimension tables.

    Args:
        session: Optional SQLAlchemy session. If not provided, creates a new one.
    """
    from database.connection import SessionLocal

    owns_session = session is None
    if owns_session:
        session = SessionLocal()

    try:
        print("[Seeding] Starting seeding process...")
        load_dim_squad(session)
        load_dim_status(session)
        load_dim_calendario(session)
        load_dim_tags(session)
        session.commit()
        print("[Seeding] Seeding completed successfully.")
    except Exception as e:
        session.rollback()
        print(f"[Seeding] Seeding failed: {e}")
        raise
    finally:
        if owns_session:
            session.close()


__all__ = [
    "seed_all",
    "load_dim_squad",
    "load_dim_status",
    "load_dim_calendario",
    "load_dim_tags",
]
