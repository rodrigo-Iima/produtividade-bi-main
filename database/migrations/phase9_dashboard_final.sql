-- Camada final de horas do dashboard Gestão à Vista.
-- Fonte: fato_clockify_entry, com Squad/Papel snapshot do lançamento.
-- Sprint: sobreposição exata de intervalo + ponte Sprint × Squad derivada dos
-- quick filters.

BEGIN;

DROP VIEW IF EXISTS
    public.vw_dashboard_sprint_squad,
    public.vw_dashboard_entry_final
CASCADE;

CREATE VIEW public.vw_dashboard_sprint_squad AS
SELECT
    b.sprint_id,
    s.sprint_name,
    s.sprint_start,
    s.sprint_end,
    s.sprint_state,
    b.board_id,
    b.squad_id,
    sq.nome AS squad_name,
    b.quick_filter_id,
    q.name AS quick_filter_name,
    q.jql AS quick_filter_jql,
    b.mapping_source,
    b.mapped_at
FROM public.bridge_sprint_squad AS b
JOIN public.dim_sprint AS s
  ON s.sprint_id = b.sprint_id
JOIN public.dim_squad AS sq
  ON sq.squad_id = b.squad_id
LEFT JOIN public.dim_jira_quick_filter AS q
  ON q.board_id = b.board_id
 AND q.quick_filter_id = b.quick_filter_id;

COMMENT ON VIEW public.vw_dashboard_sprint_squad IS
    'Auditoria da ponte Sprint × Squad. Uma Sprint compartilhada possui uma linha por Squad.';

CREATE VIEW public.vw_dashboard_entry_final AS
WITH sprint_windows AS (
    SELECT
        b.squad_id,
        s.sprint_id,
        s.sprint_name,
        s.sprint_start,
        s.sprint_end,
        s.sprint_state,
        LEAD(s.sprint_start) OVER (
            PARTITION BY b.squad_id
            ORDER BY s.sprint_start
        ) AS next_sprint_start
    FROM public.dim_sprint AS s
    JOIN (
        SELECT DISTINCT sprint_id, squad_id
        FROM public.bridge_sprint_squad
    ) AS b
      ON b.sprint_id = s.sprint_id
    WHERE s.sprint_start >= (
              TIMESTAMP '2026-01-01 00:00:00'
              AT TIME ZONE 'America/Sao_Paulo'
          )
      AND s.sprint_start <= CURRENT_TIMESTAMP
      AND LOWER(s.sprint_state) IN ('active', 'closed')
), period_candidates AS (
    SELECT
        eb.entry_id,
        s.sprint_id,
        s.sprint_name,
        s.sprint_start,
        s.sprint_end,
        s.sprint_state
    FROM public.vw_dashboard_entry_base AS eb
    JOIN sprint_windows AS s
      ON eb.collaborator_squad_id = s.squad_id
     AND eb.collaborator_squad_name <> 'Transversal'
     AND eb.started_at IS NOT NULL
     AND eb.started_at >= s.sprint_start
     AND eb.started_at < COALESCE(
             s.next_sprint_start,
             s.sprint_end,
             CURRENT_TIMESTAMP
         )
), period_rollup AS (
    SELECT
        entry_id,
        COUNT(DISTINCT sprint_id) AS sprint_candidate_count,
        MIN(sprint_id) AS period_sprint_id,
        MIN(sprint_name) AS period_sprint_name,
        MIN(sprint_start) AS period_sprint_start,
        MIN(sprint_end) AS period_sprint_end,
        MIN(sprint_state) AS period_sprint_state
    FROM period_candidates
    GROUP BY entry_id
), squad_timeline AS (
    SELECT
        b.squad_id,
        MIN(s.sprint_start) AS first_sprint_start
    FROM public.bridge_sprint_squad AS b
    JOIN public.dim_sprint AS s
      ON s.sprint_id = b.sprint_id
    WHERE s.sprint_start >= (
              TIMESTAMP '2026-01-01 00:00:00'
              AT TIME ZONE 'America/Sao_Paulo'
          )
      AND s.sprint_start <= CURRENT_TIMESTAMP
      AND LOWER(s.sprint_state) IN ('active', 'closed')
    GROUP BY b.squad_id
)
SELECT
    eb.entry_id,
    eb.entry_date,
    eb.entry_date_local,
    eb.started_at,
    eb.ended_at,
    eb.duration_seconds,
    eb.duration_hours,
    eb.user_id,
    eb.collaborator_name,
    eb.papel,
    eb.collaborator_squad_id AS squad_id,
    eb.collaborator_squad_name AS squad_name,
    eb.project_name,
    eb.task_name,
    eb.has_tag,
    eb.has_ticket,
    eb.has_focus_activity,
    eb.has_focus_eligible_activity,
    eb.has_main_activity,
    eb.has_support_delivery_activity,
    eb.has_delivery_activity,
    eb.sprint_id AS ticket_sprint_id,
    eb.sprint_name AS ticket_sprint_name,
    CASE
        WHEN eb.collaborator_squad_name = 'Transversal' THEN NULL
        WHEN pr.sprint_candidate_count = 1 THEN pr.period_sprint_id
        ELSE NULL
    END AS sprint_id,
    CASE
        WHEN eb.collaborator_squad_name = 'Transversal' THEN NULL
        WHEN pr.sprint_candidate_count = 1 THEN pr.period_sprint_name
        ELSE NULL
    END AS sprint_name,
    CASE
        WHEN eb.collaborator_squad_name = 'Transversal' THEN NULL
        WHEN pr.sprint_candidate_count = 1 THEN pr.period_sprint_start
        ELSE NULL
    END AS sprint_start,
    CASE
        WHEN eb.collaborator_squad_name = 'Transversal' THEN NULL
        WHEN pr.sprint_candidate_count = 1 THEN pr.period_sprint_end
        ELSE NULL
    END AS sprint_end,
    CASE
        WHEN eb.collaborator_squad_name = 'Transversal' THEN NULL
        WHEN pr.sprint_candidate_count = 1 THEN pr.period_sprint_state
        ELSE NULL
    END AS sprint_state,
    CASE
        WHEN eb.collaborator_squad_name = 'Transversal' THEN 'nao_aplicavel'
        WHEN pr.sprint_candidate_count = 1 THEN 'atribuido'
        WHEN pr.sprint_candidate_count > 1 THEN 'ambiguo'
        WHEN st.first_sprint_start IS NULL
          OR eb.started_at < st.first_sprint_start
            THEN 'historico_sem_sprint'
        ELSE 'sem_sprint'
    END AS sprint_assignment_status,
    CASE
        WHEN eb.collaborator_squad_name = 'Transversal' THEN 0
        ELSE COALESCE(pr.sprint_candidate_count, 0)
    END AS sprint_candidate_count
FROM public.vw_dashboard_entry_base AS eb
LEFT JOIN period_rollup AS pr
  ON pr.entry_id = eb.entry_id
LEFT JOIN squad_timeline AS st
  ON st.squad_id = eb.collaborator_squad_id;

COMMENT ON VIEW public.vw_dashboard_entry_final IS
    'Grão: uma linha por lançamento Clockify. A Sprint é definida pelo started_at na janela efetiva particionada por Squad até o início da próxima Sprint da mesma Squad; Transversal é nao_aplicavel e historico_sem_sprint identifica lançamentos anteriores à primeira Sprint conhecida; ticket_sprint_id representa somente a classificação via issue Jira.';

CREATE INDEX IF NOT EXISTS ix_bridge_sprint_squad_sprint_id
    ON public.bridge_sprint_squad (sprint_id);

COMMIT;
