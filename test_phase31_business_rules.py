from database.migrations.phase31 import (
    PHASE31_VERSION,
    PROJECT_STATUS_RULE_SQL,
    UPSERT_STATUS_MAPPING_SQL,
)


def test_phase31_confirms_only_em_andamento_starts_execution():
    assert PHASE31_VERSION == 31
    assert "status_name)) = 'travado'" in PROJECT_STATUS_RULE_SQL
    assert "starts_execution = FALSE" in PROJECT_STATUS_RULE_SQL
    assert "ON CONFLICT (project_key, status_id, status_context)" in UPSERT_STATUS_MAPPING_SQL
    assert ":status_id" in UPSERT_STATUS_MAPPING_SQL
