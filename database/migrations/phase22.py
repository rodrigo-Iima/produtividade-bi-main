"""Expose the three timebox card measures at one Sprint × Squad grain."""

from sqlalchemy import Engine, text


PHASE22_VERSION = 22


TIMEBOX_CARD_VIEW_SQL = """
DROP VIEW IF EXISTS public.vw_dashboard_sprint_timebox CASCADE;

CREATE VIEW public.vw_dashboard_sprint_timebox AS
WITH point_by_user_sprint AS (
    SELECT
        c.sprint_id,
        c.user_id,
        COALESCE(SUM(p.point_worked_hours), 0) AS hours_worked,
        COUNT(p.work_date) FILTER (
            WHERE p.flow_covered IS TRUE
        ) AS flow_observed_day_count,
        COUNT(p.work_date) FILTER (
            WHERE p.flow_covered IS TRUE
              AND p.point_mark_count > 0
        ) AS flow_marked_day_count
    FROM public.vw_dashboard_sprint_capacity_detail AS c
    LEFT JOIN public.vw_conferencia_horas_dia AS p
      ON p.user_id = c.user_id
     AND p.work_date >= (
         c.sprint_start AT TIME ZONE 'America/Sao_Paulo'
     )::DATE
     AND p.work_date < c.effective_sprint_end_date
    GROUP BY c.sprint_id, c.user_id
)
SELECT
    c.sprint_id,
    c.sprint_name,
    c.sprint_start,
    c.sprint_end,
    c.sprint_completed_at,
    c.effective_sprint_end_date,
    c.sprint_state,
    c.squad_id,
    c.squad_name,
    COUNT(*) AS collaborators,
    SUM(c.calendar_business_days) AS calendar_business_days,
    SUM(c.sprint_window_business_days) AS sprint_window_business_days,
    SUM(c.flow_non_working_days) AS flow_non_working_days,
    SUM(c.flow_non_working_days_applied) AS flow_non_working_days_applied,
    SUM(c.calendar_capacity_hours) AS theoretical_timebox_hours,
    SUM(c.snapshot_capacity_hours) AS snapshot_timebox_hours,
    SUM(c.flow_non_working_hours) AS timebox_excluded_hours,
    SUM(c.capacity_hours) AS timebox_hours,
    SUM(p.hours_worked) AS hours_worked,
    SUM(c.hours_logged) AS hours_logged,
    SUM(p.flow_observed_day_count) AS flow_observed_day_count,
    SUM(p.flow_marked_day_count) AS flow_marked_day_count,
    CASE
        WHEN SUM(c.capacity_hours) > 0
        THEN SUM(p.hours_worked)::NUMERIC / SUM(c.capacity_hours)
    END AS worked_timebox_pct,
    CASE
        WHEN SUM(c.capacity_hours) > 0
        THEN SUM(c.hours_logged)::NUMERIC / SUM(c.capacity_hours)
    END AS logged_timebox_pct,
    CASE
        WHEN SUM(p.hours_worked) > 0
        THEN SUM(c.hours_logged)::NUMERIC / SUM(p.hours_worked)
    END AS clockify_to_point_pct
FROM public.vw_dashboard_sprint_capacity_detail AS c
JOIN point_by_user_sprint AS p
  ON p.sprint_id = c.sprint_id
 AND p.user_id = c.user_id
GROUP BY
    c.sprint_id,
    c.sprint_name,
    c.sprint_start,
    c.sprint_end,
    c.sprint_completed_at,
    c.effective_sprint_end_date,
    c.sprint_state,
    c.squad_id,
    c.squad_name;

COMMENT ON VIEW public.vw_dashboard_sprint_timebox IS
    'Grão: Sprint × Squad. timebox_hours usa a janela real de conclusão; hours_worked vem da conferência diária Flow × Clockify, única por usuário/data; hours_logged vem dos lançamentos Clockify.';

DO $grant_timebox_views$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'produtividade_reader'
    ) THEN
        GRANT SELECT ON
            public.vw_dashboard_sprint_timebox,
            public.vw_dashboard_sprint_capacity,
            public.vw_dashboard_sprint_capacity_detail,
            public.vw_dashboard_sprint_efficiency,
            public.vw_flow_ponto_dia,
            public.vw_flow_marcacao_detail,
            public.vw_conferencia_horas_dia,
            public.vw_conferencia_horas_semana,
            public.vw_fila_revisao_horas
        TO produtividade_reader;
    END IF;
END
$grant_timebox_views$;
"""


def ensure_phase22_schema(engine: Engine) -> None:
    """Create the single source view for the three timebox cards."""
    with engine.begin() as connection:
        # Replacing the view requires an ACCESS EXCLUSIVE lock. Avoid waiting
        # indefinitely for an open dashboard query during deployment.
        connection.execute(text("SET LOCAL lock_timeout = '30s'"))
        connection.execute(text("SET LOCAL statement_timeout = '5min'"))
        connection.execute(text(TIMEBOX_CARD_VIEW_SQL))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE22_VERSION},
        )
