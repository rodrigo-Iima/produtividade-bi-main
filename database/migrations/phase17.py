"""Create the Flow identity and contract dimensions."""

from sqlalchemy import Engine, text


PHASE17_VERSION = 17


FLOW_IDENTITY_SQL = """
ALTER TABLE public.dim_colaborador
ADD COLUMN IF NOT EXISTS email VARCHAR(320);

CREATE INDEX IF NOT EXISTS ix_dim_colaborador_email
    ON public.dim_colaborador (email);

CREATE TABLE IF NOT EXISTS public.dim_flow_pessoa (
    flow_person_id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    social_name VARCHAR(200),
    corporate_email VARCHAR(320),
    email VARCHAR(320),
    clockify_user_id VARCHAR(100) UNIQUE
        REFERENCES public.dim_colaborador(user_id) ON DELETE SET NULL,
    mapping_status VARCHAR(40) NOT NULL DEFAULT 'unmapped_no_match',
    mapping_method VARCHAR(30),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    flow_last_seen_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_dim_flow_pessoa_mapping_status
        CHECK (
            mapping_status IN (
                'mapped',
                'unmapped_no_email',
                'unmapped_no_match',
                'ambiguous_email'
            )
        ),
    CONSTRAINT ck_dim_flow_pessoa_mapping_method
        CHECK (
            mapping_method IS NULL
            OR mapping_method IN ('corporate_email', 'email', 'manual')
        ),
    CONSTRAINT ck_dim_flow_pessoa_mapping_consistency
        CHECK (
            (
                mapping_status = 'mapped'
                AND clockify_user_id IS NOT NULL
                AND mapping_method IS NOT NULL
            )
            OR (
                mapping_status <> 'mapped'
                AND clockify_user_id IS NULL
                AND mapping_method IS NULL
            )
        )
);

CREATE INDEX IF NOT EXISTS ix_dim_flow_pessoa_corporate_email
    ON public.dim_flow_pessoa (corporate_email);
CREATE INDEX IF NOT EXISTS ix_dim_flow_pessoa_email
    ON public.dim_flow_pessoa (email);
CREATE INDEX IF NOT EXISTS ix_dim_flow_pessoa_mapping_status
    ON public.dim_flow_pessoa (mapping_status);
CREATE INDEX IF NOT EXISTS ix_dim_flow_pessoa_active
    ON public.dim_flow_pessoa (is_active);

CREATE TABLE IF NOT EXISTS public.dim_flow_contrato (
    flow_contract_id VARCHAR(100) PRIMARY KEY,
    flow_person_id VARCHAR(100) NOT NULL
        REFERENCES public.dim_flow_pessoa(flow_person_id) ON DELETE CASCADE,
    status INTEGER NOT NULL,
    admitted_at TIMESTAMPTZ,
    terminated_at TIMESTAMPTZ,
    establishment VARCHAR(200),
    role VARCHAR(200),
    function VARCHAR(200),
    work_post VARCHAR(200),
    hierarchy_circle VARCHAR(200),
    sector VARCHAR(200),
    unit VARCHAR(200),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    flow_last_seen_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_dim_flow_contrato_person
    ON public.dim_flow_contrato (flow_person_id);
CREATE INDEX IF NOT EXISTS ix_dim_flow_contrato_status
    ON public.dim_flow_contrato (status);
CREATE INDEX IF NOT EXISTS ix_dim_flow_contrato_active
    ON public.dim_flow_contrato (is_active);
"""


def ensure_phase17_schema(engine: Engine) -> None:
    """Create Flow identity tables and record the schema version."""
    with engine.begin() as connection:
        connection.execute(text(FLOW_IDENTITY_SQL))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE17_VERSION},
        )
