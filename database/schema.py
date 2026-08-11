"""Schema bootstrap and versioned PostgreSQL migrations."""

from database.connection import engine
from database.migrations.dashboard_views import ensure_dashboard_views
from database.migrations.phase2 import ensure_phase2_schema
from database.migrations.phase3 import ensure_phase3_views
from database.migrations.phase4 import ensure_phase4_schema
from database.migrations.phase5 import ensure_phase5_schema
from database.migrations.phase8 import ensure_phase8_schema
from database.migrations.phase9 import ensure_phase9_schema
from database.migrations.phase10 import ensure_phase10_schema
from database.migrations.phase11 import ensure_phase11_schema
from database.migrations.phase12 import ensure_phase12_schema
from database.migrations.phase13 import ensure_phase13_schema
from database.migrations.phase14 import ensure_phase14_schema
from database.migrations.phase15 import ensure_phase15_schema
from database.migrations.phase16 import ensure_phase16_schema
from database.migrations.phase17 import ensure_phase17_schema
from database.migrations.phase18 import ensure_phase18_schema
from database.migrations.phase19 import ensure_phase19_schema
from database.migrations.phase20 import ensure_phase20_schema
from database.migrations.phase21 import ensure_phase21_schema
from database.migrations.phase22 import ensure_phase22_schema
from database.migrations.phase23 import ensure_phase23_schema
from database.migrations.phase24 import ensure_phase24_schema


def ensure_schema() -> None:
    """Create or migrate the complete single-host EC2 schema."""
    _ensure_complete_schema()


def ensure_portable_schema() -> None:
    """Create the same complete schema in containerized environments."""
    _ensure_complete_schema()


def _ensure_complete_schema() -> None:
    """Apply tables and views in their dependency order."""
    ensure_phase2_schema(engine)
    ensure_phase5_schema(engine)
    ensure_phase8_schema(engine)
    ensure_phase9_schema(engine)
    ensure_phase10_schema(engine)
    ensure_phase11_schema(engine)
    ensure_phase12_schema(engine)
    ensure_phase13_schema(engine)
    ensure_phase14_schema(engine)
    ensure_phase16_schema(engine)
    ensure_phase17_schema(engine)
    ensure_phase18_schema(engine)
    ensure_phase20_schema(engine)
    ensure_phase23_schema(engine)
    # The dashboard SQL is recreated below and expects this source column to
    # exist before its views are compiled.
    ensure_phase24_schema(engine)
    ensure_phase19_schema(engine)
    ensure_phase3_views(engine)
    ensure_phase4_schema(engine)
    ensure_dashboard_views(engine)
    ensure_phase15_schema(engine)
    ensure_phase21_schema(engine)
    ensure_phase22_schema(engine)
