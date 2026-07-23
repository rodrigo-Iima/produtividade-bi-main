"""Create dashboard views for Sprint capacity and efficiency."""

from sqlalchemy import Engine, text


PHASE15_VERSION = 15


CAPACITY_VIEWS_SQL = """
DROP VIEW IF EXISTS
    public.vw_dashboard_sprint_efficiency,
    public.vw_dashboard_sprint_capacity,
    public.vw_dashboard_sprint_capacity_detail
CASCADE;

CREATE VIEW public.vw_dashboard_sprint_capacity_detail AS
WITH entry_by_user_sprint AS (
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
)
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
    c.business_days,
    c.capacity_hours,
    c.source AS capacity_source,
    c.calculated_at,
    COALESCE(e.entry_count, 0) AS entry_count,
    COALESCE(e.entries_with_ticket, 0) AS entries_with_ticket,
    COALESCE(e.hours_logged, 0) AS hours_logged,
    COALESCE(e.hours_with_ticket, 0) AS hours_with_ticket,
    COALESCE(e.hours_without_ticket, 0) AS hours_without_ticket,
    COALESCE(e.hours_focus, 0) AS hours_focus,
    COALESCE(e.hours_main_activity, 0) AS hours_main_activity,
    COALESCE(e.hours_support_delivery, 0) AS hours_support_delivery
FROM public.fato_sprint_capacidade AS c
JOIN public.dim_sprint AS s
  ON s.sprint_id = c.sprint_id
JOIN public.dim_colaborador AS col
  ON col.user_id = c.user_id
LEFT JOIN entry_by_user_sprint AS e
  ON e.sprint_id = c.sprint_id
 AND e.user_id = c.user_id;

COMMENT ON VIEW public.vw_dashboard_sprint_capacity_detail IS
    'Grão: colaborador × Sprint. Capacidade vem do Clockify; horas vêm dos lançamentos atribuídos à janela efetiva da Sprint.';

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
    'Grão: Sprint × Squad. Use para cards de capacidade e eficiência; percentuais são razões entre 0 e 1.';

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
    'Grão: Sprint × Squad × Papel × grupo de capacidade. Adequada para filtros de capacidade e detalhamento.';
"""


def ensure_phase15_schema(engine: Engine) -> None:
    """Create the capacity views after the final entry view exists."""
    with engine.begin() as connection:
        connection.execute(text(CAPACITY_VIEWS_SQL))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE15_VERSION},
        )
