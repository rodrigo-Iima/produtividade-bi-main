from database.migrations.phase26 import PRODUCTIVITY_CONTRACT_VIEWS_SQL


def test_phase26_creates_all_grain_safe_productivity_views():
    expected_views = (
        "vw_dashboard_entry_tag_metrics",
        "vw_dashboard_ticket_actual_hours",
        "vw_dashboard_sprint_timebox_detail",
        "vw_dashboard_data_freshness",
    )

    for view_name in expected_views:
        assert f"CREATE VIEW public.{view_name}" in PRODUCTIVITY_CONTRACT_VIEWS_SQL
        assert f"public.{view_name}" in PRODUCTIVITY_CONTRACT_VIEWS_SQL


def test_phase26_splits_expanded_facts_before_aggregation():
    assert "allocated_duration_hours" in PRODUCTIVITY_CONTRACT_VIEWS_SQL
    assert "COUNT(*) OVER (PARTITION BY bi.entry_id)" in PRODUCTIVITY_CONTRACT_VIEWS_SQL
    assert "duration_hours / NULLIF(eis.linked_issue_count, 0)" in PRODUCTIVITY_CONTRACT_VIEWS_SQL
    assert "vw_conferencia_horas_dia" in PRODUCTIVITY_CONTRACT_VIEWS_SQL
    assert "vw_flow_ponto_dia" not in PRODUCTIVITY_CONTRACT_VIEWS_SQL


def test_phase26_exposes_readonly_grants_and_freshness_audit():
    assert "GRANT SELECT ON" in PRODUCTIVITY_CONTRACT_VIEWS_SQL
    assert "produtividade_reader" in PRODUCTIVITY_CONTRACT_VIEWS_SQL
    assert "etl_run_log" in PRODUCTIVITY_CONTRACT_VIEWS_SQL
    assert "last_success_at" in PRODUCTIVITY_CONTRACT_VIEWS_SQL
