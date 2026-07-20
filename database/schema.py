"""Schema bootstrap and versioned PostgreSQL migrations."""

from database.connection import engine
from database.migrations.phase2 import ensure_phase2_schema
from database.migrations.phase3 import ensure_phase3_views
from database.migrations.phase4 import ensure_phase4_schema
from database.migrations.phase5 import ensure_phase5_schema


def ensure_schema() -> None:
    """Create or migrate the current schema."""
    ensure_phase2_schema(engine)
    ensure_phase5_schema(engine)
    ensure_phase3_views(engine)
    ensure_phase4_schema(engine)
