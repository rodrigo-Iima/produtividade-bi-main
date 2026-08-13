from database.migrations.phase27 import (
    DEPRECATED_TABLES,
    DEPRECATED_VIEWS,
    PHASE27_VERSION,
)


def test_phase27_declares_the_complete_compatibility_cleanup():
    assert PHASE27_VERSION == 27
    assert set(DEPRECATED_VIEWS) == {
        "vw_dashboard_entry_base",
        "vw_jira_ticket_sprint_detail",
        "vw_clockify_entry_detail",
        "vw_clockify_entry_tag_detail",
        "vw_clockify_entry_sprint_detail",
        "vw_clockify_entry_issue_detail",
    }
    assert set(DEPRECATED_TABLES) == {
        "dim_calendario",
        "fato_sprint_capacidade",
        "etl_view_version",
    }
