from database.migrations.phase28 import PHASE28_VERSION, PORTFOLIO_MODEL_SQL
from models.bridge_jira_issue_parent import BridgeJiraIssueParent
from models.dim_jira_status_mapping import DimJiraStatusMapping
from models.dim_ticket_jira import DimTicketJira
from models.etl_source_state import EtlSourceState
from models.fato_jira_status_transicao import FatoJiraStatusTransicao


def test_phase28_declares_the_portfolio_storage_contract():
    assert PHASE28_VERSION == 28
    for table_name in (
        "bridge_jira_issue_parent",
        "fato_jira_status_transicao",
        "dim_jira_status_mapping",
        "etl_source_state",
    ):
        assert f"public.{table_name}" in PORTFOLIO_MODEL_SQL

    for column_name in (
        "parent_issue_key",
        "planned_start_date",
        "due_date",
        "last_seen_at",
        "source_present",
        "loaded_at",
    ):
        assert column_name in PORTFOLIO_MODEL_SQL

    assert "UNIQUE (issue_key, transition_key)" in PORTFOLIO_MODEL_SQL
    assert "ck_etl_source_state_status" in PORTFOLIO_MODEL_SQL
    assert "ck_etl_source_state_rows_processed" in PORTFOLIO_MODEL_SQL
    assert "watermark_at" in PORTFOLIO_MODEL_SQL
    assert "REVOKE ALL ON" in PORTFOLIO_MODEL_SQL
    assert "produtividade_reader" in PORTFOLIO_MODEL_SQL


def test_models_expose_the_same_new_fields():
    assert {
        "parent_issue_key",
        "planned_start_date",
        "due_date",
        "last_seen_at",
        "source_present",
        "loaded_at",
    } <= set(DimTicketJira.__table__.c.keys())
    assert set(BridgeJiraIssueParent.__table__.primary_key.columns.keys()) == {
        "child_issue_key",
        "parent_issue_key",
        "relationship_type",
    }
    assert "transition_key" in FatoJiraStatusTransicao.__table__.c
    assert {
        "project_key",
        "status_id",
        "status_context",
        "starts_execution",
        "is_completion",
    } <= set(DimJiraStatusMapping.__table__.c.keys())
    assert {
        "source_name",
        "pipeline_name",
        "watermark_at",
        "watermark_value",
        "status",
    } <= set(EtlSourceState.__table__.c.keys())
