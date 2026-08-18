"""Create the Jira portfolio model and independent source checkpoints.

Phase 28 is deliberately limited to the durable storage contract. Extraction
of parent fields and changelog status events is implemented in later phases;
the tables below let those loaders be incremental and auditable without
changing the existing productivity views.
"""

from sqlalchemy import Engine, text


PHASE28_VERSION = 28


PORTFOLIO_MODEL_SQL = """
ALTER TABLE public.dim_ticket_jira
    ADD COLUMN IF NOT EXISTS parent_issue_key VARCHAR(30),
    ADD COLUMN IF NOT EXISTS planned_start_date DATE,
    ADD COLUMN IF NOT EXISTS due_date DATE,
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source_present BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;

CREATE INDEX IF NOT EXISTS ix_dim_ticket_jira_parent_issue_key
    ON public.dim_ticket_jira (parent_issue_key);
CREATE INDEX IF NOT EXISTS ix_dim_ticket_jira_project_key
    ON public.dim_ticket_jira (project_key);
CREATE INDEX IF NOT EXISTS ix_dim_ticket_jira_planned_start_date
    ON public.dim_ticket_jira (planned_start_date);
CREATE INDEX IF NOT EXISTS ix_dim_ticket_jira_due_date
    ON public.dim_ticket_jira (due_date);
CREATE INDEX IF NOT EXISTS ix_dim_ticket_jira_updated_at
    ON public.dim_ticket_jira (updated_at);
CREATE INDEX IF NOT EXISTS ix_dim_ticket_jira_source_present
    ON public.dim_ticket_jira (source_present);

COMMENT ON COLUMN public.dim_ticket_jira.parent_issue_key IS
    'Direct Jira parent when available; legacy Epic Link is normalized in bridge_jira_issue_parent.';
COMMENT ON COLUMN public.dim_ticket_jira.planned_start_date IS
    'Planned project start date supplied by Jira customfield_11167 or the configured equivalent.';
COMMENT ON COLUMN public.dim_ticket_jira.due_date IS
    'Jira due date (date only).';
COMMENT ON COLUMN public.dim_ticket_jira.last_seen_at IS
    'Last successful observation of this ticket in the Jira source.';
COMMENT ON COLUMN public.dim_ticket_jira.source_present IS
    'False when reconciliation confirms that the ticket is no longer returned by Jira.';
COMMENT ON COLUMN public.dim_ticket_jira.loaded_at IS
    'Timestamp at which the current warehouse row was first created.';

CREATE TABLE IF NOT EXISTS public.bridge_jira_issue_parent (
    child_issue_key VARCHAR(30) NOT NULL,
    parent_issue_key VARCHAR(30) NOT NULL,
    relationship_type VARCHAR(30) NOT NULL,
    source_present BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen_at TIMESTAMPTZ,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_bridge_jira_issue_parent
        PRIMARY KEY (child_issue_key, parent_issue_key, relationship_type)
);

DO $bridge_parent_constraints$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.bridge_jira_issue_parent'::regclass
          AND conname = 'ck_bridge_jira_issue_parent_distinct'
    ) THEN
        ALTER TABLE public.bridge_jira_issue_parent
            ADD CONSTRAINT ck_bridge_jira_issue_parent_distinct
            CHECK (child_issue_key <> parent_issue_key);
    END IF;
END
$bridge_parent_constraints$;

CREATE INDEX IF NOT EXISTS ix_bridge_jira_issue_parent_parent
    ON public.bridge_jira_issue_parent (parent_issue_key);
CREATE INDEX IF NOT EXISTS ix_bridge_jira_issue_parent_child
    ON public.bridge_jira_issue_parent (child_issue_key);
CREATE INDEX IF NOT EXISTS ix_bridge_jira_issue_parent_relationship
    ON public.bridge_jira_issue_parent (relationship_type);
CREATE INDEX IF NOT EXISTS ix_bridge_jira_issue_parent_last_seen
    ON public.bridge_jira_issue_parent (last_seen_at);
-- The model classes expose column-level indexes for ORM convenience. The
-- migration keeps only the composite/contract indexes above so the schema
-- does not accumulate redundant btree structures on a large bridge.
DROP INDEX IF EXISTS public.ix_bridge_jira_issue_parent_last_seen_at;

COMMENT ON TABLE public.bridge_jira_issue_parent IS
    'Grão: uma aresta child -> parent da hierarquia Jira. Não possui FK intencionalmente para preservar órfãos de fonte durante reconciliação.';

CREATE TABLE IF NOT EXISTS public.fato_jira_status_transicao (
    transition_id BIGSERIAL PRIMARY KEY,
    issue_key VARCHAR(30) NOT NULL,
    transition_key VARCHAR(255) NOT NULL,
    transition_at TIMESTAMPTZ NOT NULL,
    from_status_id VARCHAR(100),
    from_status_name VARCHAR(200),
    to_status_id VARCHAR(100),
    to_status_name VARCHAR(200),
    author_account_id VARCHAR(255),
    author_name VARCHAR(200),
    source_present BOOLEAN NOT NULL DEFAULT TRUE,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fato_jira_status_transicao_source
        UNIQUE (issue_key, transition_key)
);

DO $status_transition_constraints$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.fato_jira_status_transicao'::regclass
          AND conname = 'uq_fato_jira_status_transicao_source'
    ) THEN
        ALTER TABLE public.fato_jira_status_transicao
            ADD CONSTRAINT uq_fato_jira_status_transicao_source
            UNIQUE (issue_key, transition_key);
    END IF;
END
$status_transition_constraints$;

CREATE INDEX IF NOT EXISTS ix_fato_jira_status_transicao_issue_at
    ON public.fato_jira_status_transicao (issue_key, transition_at);
CREATE INDEX IF NOT EXISTS ix_fato_jira_status_transicao_transition_at
    ON public.fato_jira_status_transicao (transition_at);
CREATE INDEX IF NOT EXISTS ix_fato_jira_status_transicao_to_status
    ON public.fato_jira_status_transicao (to_status_id);
CREATE INDEX IF NOT EXISTS ix_fato_jira_status_transicao_source_present
    ON public.fato_jira_status_transicao (source_present);
DROP INDEX IF EXISTS public.ix_fato_jira_status_transicao_issue_key;
DROP INDEX IF EXISTS public.ix_fato_jira_status_transicao_to_status_id;

COMMENT ON TABLE public.fato_jira_status_transicao IS
    'Grão: uma transição de status por issue. transition_key é a chave idempotente derivada do changelog Jira.';

CREATE TABLE IF NOT EXISTS public.dim_jira_status_mapping (
    project_key VARCHAR(20) NOT NULL DEFAULT '*',
    status_id VARCHAR(100) NOT NULL,
    status_context VARCHAR(50) NOT NULL DEFAULT 'global',
    status_name VARCHAR(200) NOT NULL,
    status_group VARCHAR(50) NOT NULL,
    starts_execution BOOLEAN NOT NULL DEFAULT FALSE,
    is_completion BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    source VARCHAR(30) NOT NULL DEFAULT 'manual',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_dim_jira_status_mapping
        PRIMARY KEY (project_key, status_id, status_context)
);

CREATE INDEX IF NOT EXISTS ix_dim_jira_status_mapping_status_id
    ON public.dim_jira_status_mapping (status_id);
CREATE INDEX IF NOT EXISTS ix_dim_jira_status_mapping_status_group
    ON public.dim_jira_status_mapping (status_group);
CREATE INDEX IF NOT EXISTS ix_dim_jira_status_mapping_active
    ON public.dim_jira_status_mapping (is_active);
DROP INDEX IF EXISTS public.ix_dim_jira_status_mapping_is_active;

COMMENT ON TABLE public.dim_jira_status_mapping IS
    'Mapeamento funcional de status Jira por projeto/contexto; a linha de projeto * é o fallback global.';

CREATE TABLE IF NOT EXISTS public.etl_source_state (
    source_name VARCHAR(80) PRIMARY KEY,
    pipeline_name VARCHAR(80) NOT NULL,
    watermark_at TIMESTAMPTZ,
    watermark_value VARCHAR(255),
    last_success_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,
    last_record_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'never_run',
    rows_processed BIGINT NOT NULL DEFAULT 0,
    error_code VARCHAR(100),
    error_message VARCHAR(2000),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_etl_source_state_status
        CHECK (status IN ('never_run', 'running', 'success', 'partial', 'failed')),
    CONSTRAINT ck_etl_source_state_rows_processed
        CHECK (rows_processed >= 0)
);

DO $source_state_constraints$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.etl_source_state'::regclass
          AND conname = 'ck_etl_source_state_status'
    ) THEN
        ALTER TABLE public.etl_source_state
            ADD CONSTRAINT ck_etl_source_state_status
            CHECK (status IN ('never_run', 'running', 'success', 'partial', 'failed'));
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.etl_source_state'::regclass
          AND conname = 'ck_etl_source_state_rows_processed'
    ) THEN
        ALTER TABLE public.etl_source_state
            ADD CONSTRAINT ck_etl_source_state_rows_processed
            CHECK (rows_processed >= 0);
    END IF;
END
$source_state_constraints$;

CREATE INDEX IF NOT EXISTS ix_etl_source_state_pipeline_status
    ON public.etl_source_state (pipeline_name, status);
CREATE INDEX IF NOT EXISTS ix_etl_source_state_watermark_at
    ON public.etl_source_state (watermark_at);
DROP INDEX IF EXISTS public.ix_etl_source_state_pipeline_name;

COMMENT ON TABLE public.etl_source_state IS
    'Checkpoint independente por fonte/pipeline; permite retomar Jira issues, changelog e demais cargas sem compartilhar watermark.';

DO $phase28_grants$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'produtividade_etl'
    ) THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON
            public.bridge_jira_issue_parent,
            public.fato_jira_status_transicao,
            public.dim_jira_status_mapping,
            public.etl_source_state
        TO produtividade_etl;

        IF to_regclass('public.fato_jira_status_transicao_transition_id_seq') IS NOT NULL THEN
            GRANT USAGE, SELECT ON SEQUENCE
                public.fato_jira_status_transicao_transition_id_seq
            TO produtividade_etl;
        END IF;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'produtividade_reader'
    ) THEN
        GRANT USAGE ON SCHEMA public TO produtividade_reader;
        REVOKE ALL ON
            public.bridge_jira_issue_parent,
            public.fato_jira_status_transicao,
            public.dim_jira_status_mapping,
            public.etl_source_state
        FROM produtividade_reader;
    END IF;
END
$phase28_grants$;
"""


def ensure_phase28_schema(engine: Engine) -> None:
    """Install the idempotent Jira portfolio storage contract."""
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '30s'"))
        connection.execute(text("SET LOCAL statement_timeout = '5min'"))
        connection.execute(text(PORTFOLIO_MODEL_SQL))
        connection.execute(
            text(
                "INSERT INTO public.etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE28_VERSION},
        )
