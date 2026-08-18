from database.migrations.phase21 import FLOW_AWARE_CAPACITY_VIEWS_SQL
from database.migrations.phase25 import CANONICAL_ENTRY_CONTRACT_SQL
from database.migrations.phase32 import PHASE32_VERSION
from database.migrations.sprint_window import (
    SPRINT_WINDOW_REPLACE_SQL,
    SPRINT_WINDOW_VIEW_SQL,
)


def test_sprint_window_uses_planned_next_and_early_close_limits():
    assert "LEAD(ss.sprint_start_date)" in SPRINT_WINDOW_VIEW_SQL
    assert "ORDER BY ss.sprint_start_date, ss.sprint_id" in SPRINT_WINDOW_VIEW_SQL
    assert "LEAST(" in SPRINT_WINDOW_VIEW_SQL
    assert "completed_date < os.planned_end_date" in SPRINT_WINDOW_VIEW_SQL
    assert "effective_sprint_end_date" in SPRINT_WINDOW_VIEW_SQL
    assert "effective_sprint_end_at" in SPRINT_WINDOW_VIEW_SQL


def test_entry_final_uses_canonical_exclusive_window():
    assert "vw_dashboard_sprint_window" in CANONICAL_ENTRY_CONTRACT_SQL
    assert "es.started_at < s.effective_sprint_end_at" in CANONICAL_ENTRY_CONTRACT_SQL
    assert "s.sprint_completed_at AT TIME ZONE 'America/Sao_Paulo'" not in (
        CANONICAL_ENTRY_CONTRACT_SQL
    )


def test_capacity_uses_the_same_squad_specific_window():
    assert "vw_dashboard_sprint_window" in FLOW_AWARE_CAPACITY_VIEWS_SQL
    assert "w.squad_id = c.squad_id" in FLOW_AWARE_CAPACITY_VIEWS_SQL
    assert "w.effective_sprint_end_date AS effective_end_date" in (
        FLOW_AWARE_CAPACITY_VIEWS_SQL
    )


def test_sprint_window_migration_is_versioned():
    assert PHASE32_VERSION == 32
    assert "CREATE OR REPLACE VIEW public.vw_dashboard_sprint_window" in (
        SPRINT_WINDOW_REPLACE_SQL
    )
    assert "DROP VIEW IF EXISTS" not in SPRINT_WINDOW_REPLACE_SQL
