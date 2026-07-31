"""Create paired Flow intervals and daily hours reconciliation facts."""

from sqlalchemy import Engine, text


PHASE20_VERSION = 20


HOURS_RECONCILIATION_SQL = """
CREATE TABLE IF NOT EXISTS public.fato_flow_intervalo (
    flow_person_id VARCHAR(100) NOT NULL,
    work_date DATE NOT NULL,
    pair_order INTEGER NOT NULL,
    entry_mark_order INTEGER NOT NULL,
    exit_mark_order INTEGER NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    duration_seconds BIGINT NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (flow_person_id, work_date, pair_order),
    CONSTRAINT fk_fato_flow_intervalo_dia
        FOREIGN KEY (flow_person_id, work_date)
        REFERENCES public.fato_flow_dia(flow_person_id, work_date)
        ON DELETE CASCADE,
    CONSTRAINT ck_fato_flow_intervalo_pair
        CHECK (pair_order > 0),
    CONSTRAINT ck_fato_flow_intervalo_marks
        CHECK (exit_mark_order = entry_mark_order + 1),
    CONSTRAINT ck_fato_flow_intervalo_window
        CHECK (ended_at >= started_at),
    CONSTRAINT ck_fato_flow_intervalo_duration
        CHECK (duration_seconds >= 0)
);

CREATE INDEX IF NOT EXISTS ix_fato_flow_intervalo_work_date
    ON public.fato_flow_intervalo (work_date);

CREATE TABLE IF NOT EXISTS public.fato_conferencia_horas_dia (
    user_id VARCHAR(100) NOT NULL
        REFERENCES public.dim_colaborador(user_id),
    work_date DATE NOT NULL,
    flow_person_id VARCHAR(100)
        REFERENCES public.dim_flow_pessoa(flow_person_id),
    flow_covered BOOLEAN NOT NULL,
    flow_day_kind VARCHAR(100),
    point_day_exists BOOLEAN NOT NULL,
    point_mark_count INTEGER NOT NULL,
    point_interval_count INTEGER NOT NULL,
    point_worked_seconds BIGINT NOT NULL,
    point_complete BOOLEAN NOT NULL,
    clockify_entry_count INTEGER NOT NULL,
    clockify_seconds BIGINT NOT NULL,
    delta_seconds BIGINT NOT NULL,
    tolerance_seconds BIGINT NOT NULL,
    within_tolerance BOOLEAN NOT NULL,
    adjustment_deadline DATE NOT NULL,
    reconciliation_status VARCHAR(40) NOT NULL,
    as_of_date DATE NOT NULL,
    point_collected_at TIMESTAMPTZ,
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id, work_date),
    CONSTRAINT ck_fato_conferencia_horas_nonnegative
        CHECK (
            point_mark_count >= 0
            AND point_interval_count >= 0
            AND point_worked_seconds >= 0
            AND clockify_entry_count >= 0
            AND clockify_seconds >= 0
            AND tolerance_seconds >= 0
        ),
    CONSTRAINT ck_fato_conferencia_horas_status
        CHECK (
            reconciliation_status IN (
                'fora_cobertura_flow',
                'em_andamento',
                'aguardando_ajuste_ponto',
                'pendencia_ponto_vencida',
                'aguardando_lancamento_clockify',
                'pendencia_clockify_vencida',
                'divergente_no_prazo',
                'divergente_vencido',
                'clockify_maior_no_prazo',
                'clockify_maior_vencido',
                'clockify_menor_no_prazo',
                'clockify_menor_vencido',
                'clockify_em_dia_nao_trabalhado',
                'ignorado_regra_negocio',
                'conferido',
                'sem_movimento'
            )
        )
);

ALTER TABLE public.fato_conferencia_horas_dia
ADD COLUMN IF NOT EXISTS flow_covered BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE public.fato_conferencia_horas_dia
ADD COLUMN IF NOT EXISTS flow_day_kind VARCHAR(100);

ALTER TABLE public.fato_conferencia_horas_dia
ADD COLUMN IF NOT EXISTS tolerance_seconds BIGINT NOT NULL DEFAULT 0;

ALTER TABLE public.fato_conferencia_horas_dia
ADD COLUMN IF NOT EXISTS within_tolerance BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE public.fato_conferencia_horas_dia
DROP CONSTRAINT IF EXISTS ck_fato_conferencia_horas_nonnegative;

ALTER TABLE public.fato_conferencia_horas_dia
ADD CONSTRAINT ck_fato_conferencia_horas_nonnegative
CHECK (
    point_mark_count >= 0
    AND point_interval_count >= 0
    AND point_worked_seconds >= 0
    AND clockify_entry_count >= 0
    AND clockify_seconds >= 0
    AND tolerance_seconds >= 0
);

ALTER TABLE public.fato_conferencia_horas_dia
DROP CONSTRAINT IF EXISTS ck_fato_conferencia_horas_status;

ALTER TABLE public.fato_conferencia_horas_dia
ADD CONSTRAINT ck_fato_conferencia_horas_status
CHECK (
    reconciliation_status IN (
        'fora_cobertura_flow',
        'em_andamento',
        'aguardando_ajuste_ponto',
        'pendencia_ponto_vencida',
        'aguardando_lancamento_clockify',
        'pendencia_clockify_vencida',
        'divergente_no_prazo',
        'divergente_vencido',
        'clockify_maior_no_prazo',
        'clockify_maior_vencido',
        'clockify_menor_no_prazo',
        'clockify_menor_vencido',
        'clockify_em_dia_nao_trabalhado',
        'ignorado_regra_negocio',
        'conferido',
        'sem_movimento'
    )
);

CREATE INDEX IF NOT EXISTS ix_fato_conferencia_horas_status
    ON public.fato_conferencia_horas_dia (reconciliation_status);
CREATE INDEX IF NOT EXISTS ix_fato_conferencia_horas_work_date
    ON public.fato_conferencia_horas_dia (work_date);

CREATE TABLE IF NOT EXISTS public.hist_conferencia_horas_dia (
    event_id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL
        REFERENCES public.dim_colaborador(user_id),
    work_date DATE NOT NULL,
    flow_person_id VARCHAR(100)
        REFERENCES public.dim_flow_pessoa(flow_person_id),
    change_type VARCHAR(20) NOT NULL,
    flow_covered BOOLEAN NOT NULL,
    flow_day_kind VARCHAR(100),
    point_day_exists BOOLEAN NOT NULL,
    point_mark_count INTEGER NOT NULL,
    point_interval_count INTEGER NOT NULL,
    point_worked_seconds BIGINT NOT NULL,
    point_complete BOOLEAN NOT NULL,
    clockify_entry_count INTEGER NOT NULL,
    clockify_seconds BIGINT NOT NULL,
    delta_seconds BIGINT NOT NULL,
    tolerance_seconds BIGINT NOT NULL,
    within_tolerance BOOLEAN NOT NULL,
    adjustment_deadline DATE NOT NULL,
    reconciliation_status VARCHAR(40) NOT NULL,
    as_of_date DATE NOT NULL,
    point_collected_at TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL
);

ALTER TABLE public.hist_conferencia_horas_dia
ADD COLUMN IF NOT EXISTS flow_covered BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE public.hist_conferencia_horas_dia
ADD COLUMN IF NOT EXISTS flow_day_kind VARCHAR(100);

ALTER TABLE public.hist_conferencia_horas_dia
ADD COLUMN IF NOT EXISTS tolerance_seconds BIGINT NOT NULL DEFAULT 0;

ALTER TABLE public.hist_conferencia_horas_dia
ADD COLUMN IF NOT EXISTS within_tolerance BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_hist_conferencia_horas_user_date
    ON public.hist_conferencia_horas_dia (user_id, work_date);
"""


def ensure_phase20_schema(engine: Engine) -> None:
    """Create reconciliation tables and record the schema version."""
    with engine.begin() as connection:
        connection.execute(text(HOURS_RECONCILIATION_SQL))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE20_VERSION},
        )
