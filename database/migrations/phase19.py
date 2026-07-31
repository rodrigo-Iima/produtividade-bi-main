"""Create the Flow attendance semantic views."""

from sqlalchemy import Engine, text


PHASE19_VERSION = 19


FLOW_VIEWS_SQL = """
DROP VIEW IF EXISTS
    public.vw_fila_revisao_horas,
    public.vw_conferencia_horas_semana,
    public.vw_conferencia_horas_dia,
    public.vw_flow_marcacao_detail,
    public.vw_flow_ponto_dia
CASCADE;

CREATE VIEW public.vw_flow_ponto_dia AS
SELECT
    d.flow_person_id,
    p.clockify_user_id AS user_id,
    p.name AS flow_person_name,
    c.name AS collaborator_name,
    c.papel,
    c.squad_id,
    s.nome AS squad_name,
    d.work_date,
    d.period_start,
    d.period_end,
    d.max_availability_date,
    d.day_starts_at,
    d.kind,
    d.confirmed,
    d.pending_calculation,
    d.expected_workload,
    d.errors,
    d.warnings,
    COALESCE(m.marking_count, 0) AS marking_count,
    COALESCE(i.interval_count, 0) AS interval_count,
    COALESCE(i.worked_seconds, 0) AS worked_seconds,
    COALESCE(i.worked_seconds, 0) / 3600.0 AS worked_hours,
    m.first_marked_at,
    m.last_marked_at,
    m.moments,
    d.collected_at
FROM public.fato_flow_dia AS d
JOIN public.dim_flow_pessoa AS p
  ON p.flow_person_id = d.flow_person_id
LEFT JOIN public.dim_colaborador AS c
  ON c.user_id = p.clockify_user_id
LEFT JOIN public.dim_squad AS s
  ON s.squad_id = c.squad_id
LEFT JOIN LATERAL (
    SELECT
        COUNT(*) AS marking_count,
        MIN(marked_at) AS first_marked_at,
        MAX(marked_at) AS last_marked_at,
        ARRAY_AGG(marked_at ORDER BY order_in_day) AS moments
    FROM public.fato_flow_marcacao AS marking
    WHERE marking.flow_person_id = d.flow_person_id
      AND marking.work_date = d.work_date
) AS m ON TRUE
LEFT JOIN LATERAL (
    SELECT
        COUNT(*) AS interval_count,
        SUM(duration_seconds) AS worked_seconds
    FROM public.fato_flow_intervalo AS interval
    WHERE interval.flow_person_id = d.flow_person_id
      AND interval.work_date = d.work_date
) AS i ON TRUE;

COMMENT ON VIEW public.vw_flow_ponto_dia IS
    'Grão: colaborador Flow × dia retornado. Horas vêm dos pares sequenciais de marcações; não incluem banco de horas.';

CREATE VIEW public.vw_flow_marcacao_detail AS
SELECT
    m.flow_person_id,
    p.clockify_user_id AS user_id,
    p.name AS flow_person_name,
    c.name AS collaborator_name,
    c.papel,
    c.squad_id,
    s.nome AS squad_name,
    m.work_date,
    m.order_in_day,
    m.marked_at,
    d.kind,
    d.confirmed,
    d.pending_calculation,
    m.collected_at
FROM public.fato_flow_marcacao AS m
JOIN public.fato_flow_dia AS d
  ON d.flow_person_id = m.flow_person_id
 AND d.work_date = m.work_date
JOIN public.dim_flow_pessoa AS p
  ON p.flow_person_id = m.flow_person_id
LEFT JOIN public.dim_colaborador AS c
  ON c.user_id = p.clockify_user_id
LEFT JOIN public.dim_squad AS s
  ON s.squad_id = c.squad_id;

COMMENT ON VIEW public.vw_flow_marcacao_detail IS
    'Grão: marcação de ponto ordenada por colaborador e dia.';

CREATE VIEW public.vw_conferencia_horas_dia AS
SELECT
    r.user_id,
    r.flow_person_id,
    c.name AS collaborator_name,
    c.papel,
    c.squad_id,
    s.nome AS squad_name,
    r.work_date,
    r.flow_covered,
    r.flow_day_kind,
    r.point_day_exists,
    r.point_mark_count,
    r.point_interval_count,
    r.point_worked_seconds,
    r.point_worked_seconds / 3600.0 AS point_worked_hours,
    r.point_complete,
    r.clockify_entry_count,
    r.clockify_seconds,
    r.clockify_seconds / 3600.0 AS clockify_hours,
    CASE
        WHEN r.point_complete AND r.point_worked_seconds > 0
        THEN r.clockify_seconds::NUMERIC / r.point_worked_seconds
        ELSE NULL
    END AS clockify_utilization_rate,
    CASE
        WHEN r.point_complete AND r.point_worked_seconds > 0
        THEN r.clockify_seconds::NUMERIC / r.point_worked_seconds >= 0.80
        ELSE NULL
    END AS meets_clockify_utilization_target,
    r.delta_seconds,
    r.delta_seconds / 3600.0 AS delta_hours,
    r.tolerance_seconds,
    r.tolerance_seconds / 60.0 AS tolerance_minutes,
    r.within_tolerance,
    r.adjustment_deadline,
    r.reconciliation_status,
    r.as_of_date,
    r.point_collected_at,
    r.calculated_at
FROM public.fato_conferencia_horas_dia AS r
JOIN public.dim_colaborador AS c
  ON c.user_id = r.user_id
LEFT JOIN public.dim_squad AS s
  ON s.squad_id = c.squad_id;

COMMENT ON VIEW public.vw_conferencia_horas_dia IS
    'Grão: colaborador × dia com horas canônicas do ponto, Clockify rateado por dia local, diferença assinada, tolerância, prazo e situação.';

CREATE VIEW public.vw_fila_revisao_horas AS
SELECT
    1 AS priority_order,
    'Clockify maior que o ponto'::TEXT AS review_reason,
    r.reconciliation_status,
    r.user_id,
    r.flow_person_id,
    r.collaborator_name,
    COALESCE(c.email, fp.corporate_email, fp.email) AS collaborator_email,
    r.papel,
    r.squad_id,
    r.squad_name,
    r.work_date,
    r.flow_day_kind,
    r.adjustment_deadline,
    GREATEST(r.as_of_date - r.adjustment_deadline, 0) AS days_overdue,
    r.point_mark_count,
    r.point_interval_count,
    r.point_complete,
    r.point_worked_hours,
    r.clockify_entry_count,
    r.clockify_hours,
    r.clockify_utilization_rate,
    r.meets_clockify_utilization_target,
    r.delta_hours,
    ABS(r.delta_hours) AS absolute_delta_hours,
    p.expected_workload,
    p.errors AS flow_errors,
    p.warnings AS flow_warnings,
    p.first_marked_at,
    p.last_marked_at,
    p.moments AS point_moments,
    NULL::VARCHAR(40) AS review_decision,
    NULL::TEXT AS review_notes,
    r.as_of_date,
    r.calculated_at
FROM public.vw_conferencia_horas_dia AS r
JOIN public.dim_colaborador AS c
  ON c.user_id = r.user_id
LEFT JOIN public.dim_flow_pessoa AS fp
  ON fp.flow_person_id = r.flow_person_id
LEFT JOIN public.vw_flow_ponto_dia AS p
  ON p.flow_person_id = r.flow_person_id
 AND p.work_date = r.work_date
WHERE r.reconciliation_status = 'clockify_maior_vencido';

COMMENT ON VIEW public.vw_fila_revisao_horas IS
    'Fila para revisão cuidadosa apenas de dias vencidos em que o Clockify supera o ponto além da tolerância. Demais situações permanecem nas views de conferência e no painel.';

CREATE VIEW public.vw_conferencia_horas_semana AS
SELECT
    r.user_id,
    r.flow_person_id,
    r.collaborator_name,
    r.papel,
    r.squad_id,
    r.squad_name,
    DATE_TRUNC('week', r.work_date)::DATE AS week_start,
    (DATE_TRUNC('week', r.work_date)::DATE + 6) AS week_end,
    COUNT(*) AS evaluated_day_count,
    SUM(r.point_worked_seconds) AS point_worked_seconds,
    SUM(r.point_worked_hours) AS point_worked_hours,
    SUM(r.clockify_seconds) AS clockify_seconds,
    SUM(r.clockify_hours) AS clockify_hours,
    SUM(r.delta_seconds) AS delta_seconds,
    SUM(r.delta_hours) AS delta_hours,
    SUM(
        CASE
            WHEN LOWER(COALESCE(r.flow_day_kind, '')) IN (
                'compensado',
                'compensated'
            )
            THEN r.point_worked_seconds
            ELSE 0
        END
    ) / 3600.0 AS compensated_point_hours,
    COUNT(*) FILTER (
        WHERE r.reconciliation_status = 'conferido'
    ) AS reconciled_day_count,
    COUNT(*) FILTER (
        WHERE r.reconciliation_status = 'ignorado_regra_negocio'
    ) AS ignored_day_count,
    COUNT(*) FILTER (
        WHERE r.reconciliation_status IN (
            'aguardando_ajuste_ponto',
            'pendencia_ponto_vencida',
            'aguardando_lancamento_clockify',
            'pendencia_clockify_vencida',
            'clockify_maior_no_prazo',
            'clockify_maior_vencido',
            'clockify_menor_no_prazo',
            'clockify_menor_vencido',
            'clockify_em_dia_nao_trabalhado'
        )
    ) AS pending_day_count,
    COUNT(*) FILTER (
        WHERE r.reconciliation_status = 'clockify_maior_vencido'
    ) AS attention_day_count,
    COUNT(*) FILTER (
        WHERE r.reconciliation_status IN (
            'aguardando_lancamento_clockify',
            'pendencia_clockify_vencida'
        )
    ) AS clockify_reminder_day_count,
    MAX(r.as_of_date) AS as_of_date,
    MAX(r.calculated_at) AS calculated_at
FROM public.vw_conferencia_horas_dia AS r
GROUP BY
    r.user_id,
    r.flow_person_id,
    r.collaborator_name,
    r.papel,
    r.squad_id,
    r.squad_name,
    DATE_TRUNC('week', r.work_date)::DATE;

COMMENT ON VIEW public.vw_conferencia_horas_semana IS
    'Grão: colaborador × semana; visão complementar da conferência diária, com horas compensadas separadas e contagens de pendências.';
"""


def ensure_phase19_schema(engine: Engine) -> None:
    """Create Flow semantic views and record the schema version."""
    with engine.begin() as connection:
        connection.execute(text(FLOW_VIEWS_SQL))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE19_VERSION},
        )
