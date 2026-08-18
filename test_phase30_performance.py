"""Static contract checks for the productivity performance snapshots."""

import inspect

from database.migrations.phase30 import (
    PHASE30_VERSION,
    PRODUCTIVITY_SNAPSHOT_SQL,
    refresh_phase30_snapshots,
)


def test_phase30_materializes_the_two_expensive_sources():
    assert PHASE30_VERSION == 30
    assert "CREATE MATERIALIZED VIEW public.mv_dashboard_entry_tag_metrics" in PRODUCTIVITY_SNAPSHOT_SQL
    assert "CREATE MATERIALIZED VIEW public.mv_dashboard_ticket_actual_hours" in PRODUCTIVITY_SNAPSHOT_SQL
    assert "CREATE VIEW public.vw_dashboard_entry_tag_metrics AS" in PRODUCTIVITY_SNAPSHOT_SQL
    assert "CREATE VIEW public.vw_dashboard_ticket_actual_hours AS" in PRODUCTIVITY_SNAPSHOT_SQL


def test_phase30_refresh_order_respects_dependency():
    tag_refresh = "REFRESH MATERIALIZED VIEW public.mv_dashboard_entry_tag_metrics"
    actual_refresh = "REFRESH MATERIALIZED VIEW public.mv_dashboard_ticket_actual_hours"
    assert tag_refresh in PRODUCTIVITY_SNAPSHOT_SQL
    assert actual_refresh in PRODUCTIVITY_SNAPSHOT_SQL
    assert "SECURITY DEFINER" in PRODUCTIVITY_SNAPSHOT_SQL
    assert "GRANT EXECUTE ON FUNCTION public.refresh_dashboard_snapshots()" in (
        PRODUCTIVITY_SNAPSHOT_SQL
    )
    source = inspect.getsource(refresh_phase30_snapshots)
    assert "refresh_dashboard_snapshots" in source
