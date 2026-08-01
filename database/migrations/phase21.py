"""Make Sprint capacity aware of non-working Flow days."""

from sqlalchemy import Engine, text


PHASE21_VERSION = 21


FLOW_AWARE_CAPACITY_VIEWS_SQL = """
DROP VIEW IF EXISTS
    public.vw_dashboard_sprint_efficiency,
    public.vw_dashboard_sprint_capacity,
    public.vw_dashboard_sprint_capacity_detail
CASCADE;

CREATE VIEW public.vw_dashboard_sprint_capacity_detail AS
WITH capacity_day_summary AS (
    SELECT
        c.sprint_id,
        c.user_id,
        COUNT(*) FILTER (
            WHERE EXTRACT(ISODOW FROM sprint_day.work_date) BETWEEN 1 AND 5
        )::INTEGER AS sprint_window_business_days,
        COUNT(*) FILTER (
            WHERE EXTRACT(ISODOW FROM sprint_day.work_date) BETWEEN 1 AND 5
              AND p.work_date IS NOT NULL
        )::INTEGER AS flow_observed_business_days,
        COUNT(*) FILTER (
            WHERE EXTRACT(ISODOW FROM sprint_day.work_date) BETWEEN 1 AND 5
              AND LOWER(BTRIM(COALESCE(p.kind, ''))) IN (
                  'compensado',
                  'compensated',
                  'férias',
                  'ferias',
                  'repouso remunerado',
                  'ocorrência',
                  'ocorrencia'
              )
        )::INTEGER AS flow_non_working_days
    FROM public.fato_sprint_capacidade AS c
    JOIN public.dim_sprint AS s
      ON s.sprint_id = c.sprint_id
    CROSS JOIN LATERAL generate_series(
        (s.sprint_start AT TIME ZONE 'America/Sao_Paulo')::DATE,
        ((s.sprint_end AT TIME ZONE 'America/Sao_Paulo')::DATE - 1),
        INTERVAL '1 day'
    ) AS sprint_day(work_date)
    LEFT JOIN public.vw_flow_ponto_dia AS p
      ON p.user_id = c.user_id
     AND p.work_date = sprint_day.work_date::DATE
    GROUP BY c.sprint_id, c.user_id
),
entry_by_user_sprint AS (
    SELECT
        e.sprint_id,
        e.user_id,
        COUNT(*) AS entry_count,
        SUM(e.duration_hours) AS hours_logged,
        SUM(e.duration_hours) FILTER (
            WHERE e.has_ticket IS TRUE
        ) AS hours_with_ticket,
        SUM(e.duration_hours) FILTER (
            WHERE e.has_ticket IS NOT TRUE
        ) AS hours_without_ticket,
        SUM(e.duration_hours) FILTER (
            WHERE e.has_focus_activity IS TRUE
        ) AS hours_focus,
        SUM(e.duration_hours) FILTER (
            WHERE e.has_main_activity IS TRUE
        ) AS hours_main_activity,
        SUM(e.duration_hours) FILTER (
            WHERE e.has_support_delivery_activity IS TRUE
        ) AS hours_support_delivery,
        COUNT(*) FILTER (
            WHERE e.has_ticket IS TRUE
        ) AS entries_with_ticket
    FROM public.vw_dashboard_entry_final AS e
    WHERE e.sprint_id IS NOT NULL
      AND e.sprint_assignment_status = 'atribuido'
    GROUP BY e.sprint_id, e.user_id
),
capacity_detail AS (
    SELECT
        c.sprint_id,
        s.sprint_name,
        s.sprint_start,
        s.sprint_end,
        s.sprint_state,
        c.user_id,
        col.name AS collaborator_name,
        c.squad_id,
        c.squad_name,
        c.papel,
        c.capacity_group_id,
        c.capacity_group_name,
        c.capacity_hours_week,
        c.business_days AS calendar_business_days,
        d.sprint_window_business_days,
        d.flow_observed_business_days,
        d.flow_non_working_days,
        LEAST(c.business_days, d.flow_non_working_days)
            AS flow_non_working_days_applied,
        GREATEST(
            c.business_days - LEAST(c.business_days, d.flow_non_working_days),
            0
        ) AS business_days,
        c.capacity_hours AS calendar_capacity_hours,
        (
            c.capacity_hours_week / 5.0
        ) * LEAST(c.business_days, d.flow_non_working_days)
            AS flow_non_working_hours,
        GREATEST(
            c.capacity_hours
            - (
                c.capacity_hours_week / 5.0
            ) * LEAST(c.business_days, d.flow_non_working_days),
            0
        ) AS capacity_hours,
        c.source AS capacity_source,
        c.calculated_at
    FROM public.fato_sprint_capacidade AS c
    JOIN public.dim_sprint AS s
      ON s.sprint_id = c.sprint_id
    JOIN public.dim_colaborador AS col
      ON col.user_id = c.user_id
    JOIN capacity_day_summary AS d
      ON d.sprint_id = c.sprint_id
     AND d.user_id = c.user_id
)
SELECT
    c.sprint_id,
    c.sprint_name,
    c.sprint_start,
    c.sprint_end,
    c.sprint_state,
    c.user_id,
    c.collaborator_name,
    c.squad_id,
    c.squad_name,
    c.papel,
    c.capacity_group_id,
    c.capacity_group_name,
    c.capacity_hours_week,
    c.calendar_business_days,
    c.sprint_window_business_days,
    c.flow_observed_business_days,
    c.flow_non_working_days,
    c.flow_non_working_days_applied,
    c.business_days,
    c.calendar_capacity_hours,
    c.flow_non_working_hours,
    c.capacity_hours,
    c.capacity_source,
    c.calculated_at,
    COALESCE(e.entry_count, 0) AS entry_count,
    COALESCE(e.entries_with_ticket, 0) AS entries_with_ticket,
    COALESCE(e.hours_logged, 0) AS hours_logged,
    COALESCE(e.hours_with_ticket, 0) AS hours_with_ticket,
    COALESCE(e.hours_without_ticket, 0) AS hours_without_ticket,
    COALESCE(e.hours_focus, 0) AS hours_focus,
    COALESCE(e.hours_main_activity, 0) AS hours_main_activity,
    COALESCE(e.hours_support_delivery, 0) AS hours_support_delivery
FROM capacity_detail AS c
LEFT JOIN entry_by_user_sprint AS e
  ON e.sprint_id = c.sprint_id
 AND e.user_id = c.user_id;

COMMENT ON VIEW public.vw_dashboard_sprint_capacity_detail IS
    'Grão: colaborador × Sprint. Capacidade teórica preserva o snapshot existente e desconta, no máximo, os dias Flow não trabalhados que cabem nessa capacidade; a janela atual da Sprint fica disponível para diagnóstico.';

CREATE VIEW public.vw_dashboard_sprint_capacity AS
SELECT
    sprint_id,
    sprint_name,
    sprint_start,
    sprint_end,
    sprint_state,
    squad_id,
    squad_name,
    COUNT(*) AS collaborators,
    COUNT(*) FILTER (
        WHERE capacity_group_name = '30h'
    ) AS collaborators_30h,
    COUNT(*) FILTER (
        WHERE capacity_group_name = '40h'
    ) AS collaborators_40h,
    SUM(calendar_business_days) AS calendar_business_days,
    SUM(sprint_window_business_days) AS sprint_window_business_days,
    SUM(flow_observed_business_days) AS flow_observed_business_days,
    SUM(flow_non_working_days) AS flow_non_working_days,
    SUM(flow_non_working_days_applied) AS flow_non_working_days_applied,
    SUM(business_days) AS business_days,
    SUM(calendar_capacity_hours) AS calendar_capacity_hours,
    SUM(flow_non_working_hours) AS flow_non_working_hours,
    SUM(capacity_hours) AS capacity_hours,
    SUM(capacity_hours) FILTER (
        WHERE capacity_group_name = '30h'
    ) AS capacity_hours_30h,
    SUM(capacity_hours) FILTER (
        WHERE capacity_group_name = '40h'
    ) AS capacity_hours_40h,
    SUM(hours_logged) AS hours_logged,
    SUM(hours_with_ticket) AS hours_with_ticket,
    SUM(hours_without_ticket) AS hours_without_ticket,
    SUM(hours_focus) AS hours_focus,
    SUM(hours_main_activity) AS hours_main_activity,
    SUM(hours_support_delivery) AS hours_support_delivery,
    CASE
        WHEN SUM(capacity_hours) > 0
        THEN SUM(hours_logged)::numeric / SUM(capacity_hours)
    END AS utilization_pct,
    CASE
        WHEN SUM(capacity_hours) > 0
        THEN SUM(hours_with_ticket)::numeric / SUM(capacity_hours)
    END AS ticket_capacity_pct,
    CASE
        WHEN SUM(capacity_hours) > 0
        THEN SUM(hours_focus)::numeric / SUM(capacity_hours)
    END AS focus_capacity_pct,
    CASE
        WHEN SUM(capacity_hours) > 0
        THEN SUM(hours_main_activity)::numeric / SUM(capacity_hours)
    END AS main_activity_capacity_pct,
    CASE
        WHEN SUM(capacity_hours) > 0
        THEN SUM(hours_support_delivery)::numeric / SUM(capacity_hours)
    END AS support_delivery_capacity_pct
FROM public.vw_dashboard_sprint_capacity_detail
GROUP BY
    sprint_id,
    sprint_name,
    sprint_start,
    sprint_end,
    sprint_state,
    squad_id,
    squad_name;

COMMENT ON VIEW public.vw_dashboard_sprint_capacity IS
    'Grão: Sprint × Squad. capacity_hours é a capacidade efetiva após os dias não trabalhados identificados no Flow; calendar_capacity_hours preserva o valor teórico.';

CREATE VIEW public.vw_dashboard_sprint_efficiency AS
SELECT
    sprint_id,
    sprint_name,
    sprint_start,
    sprint_end,
    sprint_state,
    squad_id,
    squad_name,
    papel,
    capacity_group_id,
    capacity_group_name,
    COUNT(*) AS collaborators,
    SUM(calendar_business_days) AS calendar_business_days,
    SUM(sprint_window_business_days) AS sprint_window_business_days,
    SUM(flow_observed_business_days) AS flow_observed_business_days,
    SUM(flow_non_working_days) AS flow_non_working_days,
    SUM(flow_non_working_days_applied) AS flow_non_working_days_applied,
    SUM(business_days) AS business_days,
    SUM(calendar_capacity_hours) AS calendar_capacity_hours,
    SUM(flow_non_working_hours) AS flow_non_working_hours,
    SUM(capacity_hours) AS capacity_hours,
    SUM(hours_logged) AS hours_logged,
    SUM(hours_with_ticket) AS hours_with_ticket,
    SUM(hours_without_ticket) AS hours_without_ticket,
    SUM(hours_focus) AS hours_focus,
    SUM(hours_main_activity) AS hours_main_activity,
    SUM(hours_support_delivery) AS hours_support_delivery,
    CASE
        WHEN SUM(capacity_hours) > 0
        THEN SUM(hours_logged)::numeric / SUM(capacity_hours)
    END AS utilization_pct,
    CASE
        WHEN SUM(capacity_hours) > 0
        THEN SUM(hours_with_ticket)::numeric / SUM(capacity_hours)
    END AS ticket_capacity_pct,
    CASE
        WHEN SUM(capacity_hours) > 0
        THEN SUM(hours_focus)::numeric / SUM(capacity_hours)
    END AS focus_capacity_pct,
    CASE
        WHEN SUM(capacity_hours) > 0
        THEN SUM(hours_main_activity)::numeric / SUM(capacity_hours)
    END AS main_activity_capacity_pct,
    CASE
        WHEN SUM(capacity_hours) > 0
        THEN SUM(hours_support_delivery)::numeric / SUM(capacity_hours)
    END AS support_delivery_capacity_pct
FROM public.vw_dashboard_sprint_capacity_detail
GROUP BY
    sprint_id,
    sprint_name,
    sprint_start,
    sprint_end,
    sprint_state,
    squad_id,
    squad_name,
    papel,
    capacity_group_id,
    capacity_group_name;

COMMENT ON VIEW public.vw_dashboard_sprint_efficiency IS
    'Grão: Sprint × Squad × Papel × grupo de capacidade; percentuais usam a capacidade efetiva após ajustes de dias Flow não trabalhados.';

DO $grant_capacity_views$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'produtividade_reader'
    ) THEN
        GRANT SELECT ON
            public.vw_dashboard_sprint_capacity_detail,
            public.vw_dashboard_sprint_capacity,
            public.vw_dashboard_sprint_efficiency
        TO produtividade_reader;
    END IF;
END
$grant_capacity_views$;
"""


def ensure_phase21_schema(engine: Engine) -> None:
    """Replace capacity views with Flow-aware effective capacity metrics."""
    with engine.begin() as connection:
        # Replacing a view requires an ACCESS EXCLUSIVE lock. Fail fast if a
        # dashboard query is still using one of the old definitions instead of
        # leaving the migration process blocked indefinitely.
        connection.execute(text("SET LOCAL lock_timeout = '30s'"))
        connection.execute(text("SET LOCAL statement_timeout = '5min'"))
        connection.execute(text(FLOW_AWARE_CAPACITY_VIEWS_SQL))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE21_VERSION},
        )
