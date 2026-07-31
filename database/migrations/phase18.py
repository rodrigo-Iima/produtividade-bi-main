"""Create Flow attendance-day and clock-marking facts."""

from sqlalchemy import Engine, text


PHASE18_VERSION = 18


FLOW_POINTS_SQL = """
CREATE TABLE IF NOT EXISTS public.fato_flow_dia (
    flow_person_id VARCHAR(100) NOT NULL
        REFERENCES public.dim_flow_pessoa(flow_person_id) ON DELETE CASCADE,
    work_date DATE NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    max_availability_date DATE,
    day_starts_at TIME,
    kind VARCHAR(100),
    confirmed BOOLEAN NOT NULL,
    pending_calculation BOOLEAN NOT NULL,
    expected_workload VARCHAR(100),
    errors JSONB NOT NULL,
    warnings JSONB NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (flow_person_id, work_date),
    CONSTRAINT ck_fato_flow_dia_period
        CHECK (period_start <= period_end),
    CONSTRAINT ck_fato_flow_dia_work_date
        CHECK (work_date BETWEEN period_start AND period_end)
);

CREATE INDEX IF NOT EXISTS ix_fato_flow_dia_work_date
    ON public.fato_flow_dia (work_date);
CREATE INDEX IF NOT EXISTS ix_fato_flow_dia_collected_at
    ON public.fato_flow_dia (collected_at);

CREATE TABLE IF NOT EXISTS public.fato_flow_marcacao (
    flow_person_id VARCHAR(100) NOT NULL,
    work_date DATE NOT NULL,
    order_in_day INTEGER NOT NULL,
    marked_at TIMESTAMPTZ NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (flow_person_id, work_date, order_in_day),
    CONSTRAINT fk_fato_flow_marcacao_dia
        FOREIGN KEY (flow_person_id, work_date)
        REFERENCES public.fato_flow_dia(flow_person_id, work_date)
        ON DELETE CASCADE,
    CONSTRAINT ck_fato_flow_marcacao_order
        CHECK (order_in_day > 0)
);

CREATE INDEX IF NOT EXISTS ix_fato_flow_marcacao_work_date
    ON public.fato_flow_marcacao (work_date);
CREATE INDEX IF NOT EXISTS ix_fato_flow_marcacao_marked_at
    ON public.fato_flow_marcacao (marked_at);
"""


def ensure_phase18_schema(engine: Engine) -> None:
    """Create Flow point facts and record the schema version."""
    with engine.begin() as connection:
        connection.execute(text(FLOW_POINTS_SQL))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE18_VERSION},
        )
