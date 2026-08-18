"""Canonical analytical window for Sprint × Squad metrics."""


SPRINT_WINDOW_VIEW_SQL = """
DROP VIEW IF EXISTS public.vw_dashboard_sprint_window CASCADE;

CREATE VIEW public.vw_dashboard_sprint_window AS
WITH sprint_squads AS (
    SELECT DISTINCT
        b.squad_id,
        s.sprint_id,
        s.sprint_name,
        s.sprint_start,
        s.sprint_end,
        s.sprint_completed_at,
        s.sprint_state,
        (s.sprint_start AT TIME ZONE 'America/Sao_Paulo')::DATE
            AS sprint_start_date,
        (s.sprint_end AT TIME ZONE 'America/Sao_Paulo')::DATE
            AS planned_end_date,
        (s.sprint_completed_at AT TIME ZONE 'America/Sao_Paulo')::DATE
            AS completed_date
    FROM public.dim_sprint AS s
    JOIN public.bridge_sprint_squad AS b
      ON b.sprint_id = s.sprint_id
    WHERE s.sprint_start >= (
              TIMESTAMP '2026-01-01 00:00:00'
              AT TIME ZONE 'America/Sao_Paulo'
          )
      AND s.sprint_start <= CURRENT_TIMESTAMP
      AND LOWER(s.sprint_state) IN ('active', 'closed')
), ordered_sprints AS (
    SELECT
        ss.*,
        LEAD(ss.sprint_start_date) OVER (
            PARTITION BY ss.squad_id
            ORDER BY ss.sprint_start_date, ss.sprint_id
        ) AS next_sprint_start_date
    FROM sprint_squads AS ss
), calculated_windows AS (
    SELECT
        os.*,
        CASE
            WHEN LOWER(os.sprint_state) = 'closed'
             AND os.completed_date IS NOT NULL
             AND os.planned_end_date IS NOT NULL
             AND os.completed_date < os.planned_end_date
            THEN os.completed_date + 1
            ELSE os.planned_end_date
        END AS early_close_end_date
    FROM ordered_sprints AS os
)
SELECT
    cw.squad_id,
    cw.sprint_id,
    cw.sprint_name,
    cw.sprint_start,
    cw.sprint_end,
    cw.sprint_completed_at,
    cw.sprint_state,
    cw.sprint_start_date,
    cw.planned_end_date,
    cw.completed_date,
    cw.next_sprint_start_date,
    cw.early_close_end_date,
    LEAST(
        cw.planned_end_date,
        cw.next_sprint_start_date,
        cw.early_close_end_date
    ) AS effective_sprint_end_date,
    (
        LEAST(
            cw.planned_end_date,
            cw.next_sprint_start_date,
            cw.early_close_end_date
        )::TIMESTAMP AT TIME ZONE 'America/Sao_Paulo'
    ) AS effective_sprint_end_at
FROM calculated_windows AS cw;

COMMENT ON VIEW public.vw_dashboard_sprint_window IS
    'Grão: Sprint × Squad. A janela é semiaberta: início inclusivo e effective_sprint_end_date exclusivo. O fim planejado limita a janela; a próxima Sprint impede sobreposição; encerramento formal só reduz a janela quando antecipado e nunca a amplia.';
"""

# The versioned migration runs after the dependent views have been rebuilt. A
# replace keeps those dependencies intact and avoids dropping the contract at
# the end of the schema bootstrap.
SPRINT_WINDOW_REPLACE_SQL = SPRINT_WINDOW_VIEW_SQL.replace(
    "DROP VIEW IF EXISTS public.vw_dashboard_sprint_window CASCADE;\n\n",
    "",
    1,
).replace(
    "CREATE VIEW public.vw_dashboard_sprint_window AS",
    "CREATE OR REPLACE VIEW public.vw_dashboard_sprint_window AS",
    1,
)
