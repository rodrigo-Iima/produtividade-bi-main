from database.migrations.phase29 import PHASE29_VERSION, PROJECT_PORTFOLIO_VIEWS_SQL


def test_phase29_installs_the_sprint_independent_project_contract():
    assert PHASE29_VERSION == 29
    for view_name in (
        "vw_dashboard_project_child",
        "vw_dashboard_project_portfolio",
        "vw_dashboard_project_freshness",
    ):
        assert f"public.{view_name}" in PROJECT_PORTFOLIO_VIEWS_SQL

    assert "fato_jira_ticket_sprint" not in PROJECT_PORTFOLIO_VIEWS_SQL
    assert "source_present = TRUE" in PROJECT_PORTFOLIO_VIEWS_SQL
    assert "original_estimate_hours" in PROJECT_PORTFOLIO_VIEWS_SQL
    assert "NO_CHILDREN" in PROJECT_PORTFOLIO_VIEWS_SQL
    assert "NO_ESTIMATES" in PROJECT_PORTFOLIO_VIEWS_SQL
    assert "PARTIAL_ESTIMATES" in PROJECT_PORTFOLIO_VIEWS_SQL
    assert "progress_availability" in PROJECT_PORTFOLIO_VIEWS_SQL
    assert "keys_without_estimate" in PROJECT_PORTFOLIO_VIEWS_SQL
    assert "actual_start_at" in PROJECT_PORTFOLIO_VIEWS_SQL
    assert "actual_end_at" in PROJECT_PORTFOLIO_VIEWS_SQL
    assert "JIRA_PROJECTS" in PROJECT_PORTFOLIO_VIEWS_SQL


def test_phase29_grants_only_the_reader_contract_views():
    assert "GRANT SELECT ON" in PROJECT_PORTFOLIO_VIEWS_SQL
    assert "produtividade_reader" in PROJECT_PORTFOLIO_VIEWS_SQL
    assert "dim_ticket_jira" not in PROJECT_PORTFOLIO_VIEWS_SQL.split(
        "DO $phase29_grants$", 1
    )[1]
