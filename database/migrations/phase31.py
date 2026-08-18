"""Apply the confirmed project portfolio status semantics."""

from sqlalchemy import Engine, text

from database.seed.data import JIRA_STATUS_MAPPINGS


PHASE31_VERSION = 31


PROJECT_STATUS_RULE_SQL = """
-- "Em andamento" is the only status that starts real execution. "Travado"
-- remains an active executive bucket but cannot create an actual start date.
UPDATE public.dim_jira_status_mapping
   SET starts_execution = FALSE,
       updated_at = CURRENT_TIMESTAMP
 WHERE LOWER(TRIM(status_name)) = 'travado';
"""


UPSERT_STATUS_MAPPING_SQL = """
INSERT INTO public.dim_jira_status_mapping (
    project_key,
    status_id,
    status_context,
    status_name,
    status_group,
    starts_execution,
    is_completion,
    is_active,
    source,
    updated_at,
    loaded_at
)
VALUES (
    '*',
    :status_id,
    'global',
    :status_name,
    :status_group,
    :starts_execution,
    :is_completion,
    TRUE,
    'default',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
)
ON CONFLICT (project_key, status_id, status_context) DO UPDATE
SET status_name = EXCLUDED.status_name,
    status_group = EXCLUDED.status_group,
    starts_execution = EXCLUDED.starts_execution,
    is_completion = EXCLUDED.is_completion,
    is_active = TRUE,
    source = 'default',
    updated_at = CURRENT_TIMESTAMP;
"""


def ensure_phase31_schema(engine: Engine) -> None:
    """Persist the business-rule decision idempotently."""
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '30s'"))
        # The status mapping table was introduced after the original seed
        # flow. Upsert the canonical global rows here so a fresh install and
        # an existing database apply the same semantics without a manual seed.
        for mapping in JIRA_STATUS_MAPPINGS:
            connection.execute(text(UPSERT_STATUS_MAPPING_SQL), mapping)
        connection.execute(text(PROJECT_STATUS_RULE_SQL))
        connection.execute(
            text(
                "INSERT INTO public.etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE31_VERSION},
        )
