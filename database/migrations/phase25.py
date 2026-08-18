"""Unify the analytical view contract and permissions.

Phase 25 makes ``vw_dashboard_entry_final`` the only dashboard source for
Clockify entries.  The legacy base/detail objects remain available for one
release, but are explicitly marked deprecated and are not used by the
dashboard contract.
"""

from sqlalchemy import Engine, text

from database.migrations.sprint_window import SPRINT_WINDOW_VIEW_SQL


PHASE25_VERSION = 25


CANONICAL_ENTRY_CONTRACT_SQL = """
DROP VIEW IF EXISTS
    public.vw_dashboard_sprint_kpis,
    public.vw_dashboard_sprint_productivity,
    public.vw_dashboard_entry_sprint,
    public.vw_dashboard_entry_tag,
    public.vw_dashboard_entry_final
CASCADE;

CREATE VIEW public.vw_dashboard_entry_final AS
WITH tag_by_entry AS (
    SELECT
        e.entry_id,
        COUNT(bt.tag_id) > 0 AS has_tag,
        COALESCE(BOOL_OR(bt.foco_flag = 'Dentro do Foco'), FALSE)
            AS has_focus_activity,
        COALESCE(
            BOOL_OR(bt.foco_flag IN ('Dentro do Foco', 'Fora do Foco')),
            FALSE
        ) AS has_focus_eligible_activity,
        COALESCE(
            BOOL_OR(t.nome_normalizado = pm.tag_name_normalized),
            FALSE
        ) AS has_main_activity,
        COALESCE(
            BOOL_OR(t.nome_normalizado IN ('qa', 'dev-check')),
            FALSE
        ) AS has_support_delivery_activity,
        COALESCE(
            BOOL_OR(t.nome_normalizado IN (
                'dev', 'qa', 'dev-check',
                'analise e levantamento de requisitos'
            )),
            FALSE
        ) AS has_delivery_activity
    FROM public.fato_clockify_entry AS e
    LEFT JOIN public.dim_colaborador AS c
      ON c.user_id = e.user_id
    LEFT JOIN public.bridge_clockify_entry_tag AS bt
      ON bt.entry_id = e.entry_id
    LEFT JOIN public.dim_tag AS t
      ON t.tag_id = bt.tag_id
    LEFT JOIN public.dim_papel_atividade_principal AS pm
      ON pm.papel = COALESCE(e.papel_at_entry, c.papel)
    GROUP BY e.entry_id
), issue_by_entry AS (
    SELECT
        bi.entry_id,
        COUNT(DISTINCT bi.issue_key) > 0 AS has_ticket
    FROM public.bridge_clockify_entry_issue AS bi
    GROUP BY bi.entry_id
), entry_sprint_candidates AS (
    SELECT
        bs.entry_id,
        bs.sprint_id,
        bs.assignment_status,
        bs.assignment_reason
    FROM public.bridge_clockify_entry_sprint AS bs
    JOIN public.vw_dashboard_valid_sprint AS s
      ON s.sprint_id = bs.sprint_id
    WHERE bs.assignment_status IN ('atribuido', 'ambiguo')
), entry_sprint_rollup AS (
    SELECT
        c.entry_id,
        COUNT(DISTINCT c.sprint_id) AS sprint_candidate_count,
        CASE
            WHEN COUNT(DISTINCT c.sprint_id) = 1
             AND BOOL_OR(c.assignment_status = 'atribuido')
            THEN MIN(c.sprint_id)
        END AS ticket_sprint_id,
        MAX(c.assignment_reason) AS ticket_sprint_assignment_reason
    FROM entry_sprint_candidates AS c
    GROUP BY c.entry_id
), entry_source AS (
    SELECT
        e.entry_id,
        e.entry_date,
        e.entry_date_local,
        e.started_at,
        e.ended_at,
        e.duration_seconds,
        e.duration_seconds / 3600.0 AS duration_hours,
        e.user_id,
        c.name AS collaborator_name,
        COALESCE(e.papel_at_entry, c.papel) AS papel,
        COALESCE(e.squad_id_at_entry, c.squad_id) AS collaborator_squad_id,
        COALESCE(e.squad_name_at_entry, sq.nome) AS collaborator_squad_name,
        e.project_name,
        e.task_name,
        esr.ticket_sprint_id,
        ts.sprint_name AS ticket_sprint_name,
        COALESCE(tf.has_tag, FALSE) AS has_tag,
        COALESCE(ifl.has_ticket, FALSE) AS has_ticket,
        COALESCE(tf.has_focus_activity, FALSE) AS has_focus_activity,
        COALESCE(tf.has_focus_eligible_activity, FALSE)
            AS has_focus_eligible_activity,
        COALESCE(tf.has_main_activity, FALSE) AS has_main_activity,
        COALESCE(tf.has_support_delivery_activity, FALSE)
            AS has_support_delivery_activity,
        COALESCE(tf.has_delivery_activity, FALSE) AS has_delivery_activity,
        COALESCE(esr.sprint_candidate_count, 0) > 0 AS has_ticket_sprint,
        COALESCE(esr.ticket_sprint_assignment_reason, 'sem_sprint')
            AS ticket_sprint_assignment_reason
    FROM public.fato_clockify_entry AS e
    LEFT JOIN public.dim_colaborador AS c
      ON c.user_id = e.user_id
    LEFT JOIN public.dim_squad AS sq
      ON sq.squad_id = COALESCE(e.squad_id_at_entry, c.squad_id)
    LEFT JOIN tag_by_entry AS tf
      ON tf.entry_id = e.entry_id
    LEFT JOIN issue_by_entry AS ifl
      ON ifl.entry_id = e.entry_id
    LEFT JOIN entry_sprint_rollup AS esr
      ON esr.entry_id = e.entry_id
    LEFT JOIN public.vw_dashboard_valid_sprint AS ts
      ON ts.sprint_id = esr.ticket_sprint_id
), period_candidates AS (
    SELECT
        es.entry_id,
        s.sprint_id,
        s.sprint_name,
        s.sprint_start,
        s.sprint_end,
        s.sprint_completed_at,
        s.effective_sprint_end_at,
        s.sprint_state
    FROM entry_source AS es
    JOIN public.vw_dashboard_sprint_window AS s
      ON es.collaborator_squad_id = s.squad_id
     AND es.collaborator_squad_name <> 'Transversal'
     AND es.started_at IS NOT NULL
     AND es.started_at >= s.sprint_start
     AND es.started_at < s.effective_sprint_end_at
), period_rollup AS (
    SELECT
        entry_id,
        COUNT(DISTINCT sprint_id) AS sprint_candidate_count,
        MIN(sprint_id) AS period_sprint_id,
        MIN(sprint_name) AS period_sprint_name,
        MIN(sprint_start) AS period_sprint_start,
        MIN(sprint_end) AS period_sprint_end,
        MIN(sprint_completed_at) AS period_sprint_completed_at,
        MIN(effective_sprint_end_at) AS period_effective_sprint_end_at,
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
    es.entry_id,
    es.entry_date,
    es.entry_date_local,
    es.started_at,
    es.ended_at,
    es.duration_seconds,
    es.duration_hours,
    es.user_id,
    es.collaborator_name,
    es.papel,
    es.collaborator_squad_id AS squad_id,
    es.collaborator_squad_name AS squad_name,
    es.project_name,
    es.task_name,
    es.has_tag,
    es.has_ticket,
    es.has_focus_activity,
    es.has_focus_eligible_activity,
    es.has_main_activity,
    es.has_support_delivery_activity,
    es.has_delivery_activity,
    es.ticket_sprint_id,
    es.ticket_sprint_name,
    CASE
        WHEN es.collaborator_squad_name = 'Transversal' THEN NULL
        WHEN pr.sprint_candidate_count = 1 THEN pr.period_sprint_id
    END AS sprint_id,
    CASE
        WHEN es.collaborator_squad_name = 'Transversal' THEN NULL
        WHEN pr.sprint_candidate_count = 1 THEN pr.period_sprint_name
    END AS sprint_name,
    CASE
        WHEN es.collaborator_squad_name = 'Transversal' THEN NULL
        WHEN pr.sprint_candidate_count = 1 THEN pr.period_sprint_start
    END AS sprint_start,
    CASE
        WHEN es.collaborator_squad_name = 'Transversal' THEN NULL
        WHEN pr.sprint_candidate_count = 1 THEN pr.period_sprint_end
    END AS sprint_end,
    CASE
        WHEN es.collaborator_squad_name = 'Transversal' THEN NULL
        WHEN pr.sprint_candidate_count = 1 THEN pr.period_sprint_completed_at
    END AS sprint_completed_at,
    CASE
        WHEN es.collaborator_squad_name = 'Transversal' THEN NULL
        WHEN pr.sprint_candidate_count = 1 THEN pr.period_effective_sprint_end_at
    END AS effective_sprint_end_at,
    CASE
        WHEN es.collaborator_squad_name = 'Transversal' THEN NULL
        WHEN pr.sprint_candidate_count = 1 THEN pr.period_sprint_state
    END AS sprint_state,
    CASE
        WHEN es.collaborator_squad_name = 'Transversal' THEN 'nao_aplicavel'
        WHEN pr.sprint_candidate_count = 1 THEN 'atribuido'
        WHEN pr.sprint_candidate_count > 1 THEN 'ambiguo'
        WHEN st.first_sprint_start IS NULL
          OR es.started_at < st.first_sprint_start
        THEN 'historico_sem_sprint'
        ELSE 'sem_sprint'
    END AS sprint_assignment_status,
    CASE
        WHEN es.collaborator_squad_name = 'Transversal' THEN 0
        ELSE COALESCE(pr.sprint_candidate_count, 0)
    END AS sprint_candidate_count,
    CASE
        WHEN es.collaborator_squad_name = 'Transversal' THEN FALSE
        ELSE COALESCE(pr.sprint_candidate_count, 0) > 0
    END AS has_sprint,
    CASE
        WHEN es.collaborator_squad_name = 'Transversal' THEN 'transversal'
        WHEN pr.sprint_candidate_count = 1 THEN 'date_interval'
        WHEN pr.sprint_candidate_count > 1 THEN 'ambiguous_date_interval'
        WHEN st.first_sprint_start IS NULL
          OR es.started_at < st.first_sprint_start
        THEN 'before_first_sprint'
        ELSE 'outside_sprint_window'
    END AS sprint_assignment_reason,
    es.collaborator_squad_id,
    es.collaborator_squad_name
FROM entry_source AS es
LEFT JOIN period_rollup AS pr
  ON pr.entry_id = es.entry_id
LEFT JOIN squad_timeline AS st
  ON st.squad_id = es.collaborator_squad_id;

COMMENT ON VIEW public.vw_dashboard_entry_final IS
    'Fonte oficial de lançamentos do dashboard. Grão: uma linha por lançamento Clockify; a Sprint é atribuída exclusivamente pelo intervalo de datas da Squad. A classificação Jira fica em ticket_sprint_id apenas para auditoria. Status esperados: atribuido, ambiguo, sem_sprint, historico_sem_sprint e nao_aplicavel.';

CREATE VIEW public.vw_dashboard_entry_tag AS
WITH tag_link AS (
    SELECT
        bt.entry_id,
        bt.tag_id,
        CASE
            WHEN BOOL_OR(bt.foco_flag = 'Dentro do Foco') THEN 'Dentro do Foco'
            WHEN BOOL_OR(bt.foco_flag = 'Fora do Foco') THEN 'Fora do Foco'
            WHEN BOOL_OR(bt.foco_flag = 'Sem Papel Definido') THEN 'Sem Papel Definido'
            ELSE MAX(bt.foco_flag)
        END AS foco_flag
    FROM public.bridge_clockify_entry_tag AS bt
    GROUP BY bt.entry_id, bt.tag_id
)
SELECT
    e.entry_id,
    e.entry_date,
    e.duration_hours,
    e.user_id,
    e.collaborator_name,
    e.papel,
    e.collaborator_squad_id,
    e.collaborator_squad_name,
    e.sprint_id,
    e.sprint_name,
    e.sprint_start,
    e.sprint_end,
    e.sprint_state,
    e.sprint_assignment_status,
    tl.tag_id,
    t.nome AS tag_name,
    t.nome_normalizado AS tag_name_normalized,
    tl.foco_flag,
    (tl.foco_flag = 'Dentro do Foco') AS foco_flag_dentro
FROM public.vw_dashboard_entry_final AS e
JOIN tag_link AS tl ON tl.entry_id = e.entry_id
JOIN public.dim_tag AS t ON t.tag_id = tl.tag_id;

COMMENT ON VIEW public.vw_dashboard_entry_tag IS
    'Grão: lançamento × tag, com a Sprint oficial atribuída por intervalo de datas. A mesma hora pode aparecer em múltiplas tags.';

CREATE VIEW public.vw_dashboard_entry_sprint AS
WITH sprint_link AS (
    SELECT
        bs.entry_id,
        bs.sprint_id,
        CASE
            WHEN BOOL_OR(bs.assignment_status = 'atribuido') THEN 'atribuido'
            WHEN BOOL_OR(bs.assignment_status = 'ambiguo') THEN 'ambiguo'
            ELSE MAX(bs.assignment_status)
        END AS assignment_status,
        MAX(bs.assignment_reason) AS assignment_reason
    FROM public.bridge_clockify_entry_sprint AS bs
    JOIN public.vw_dashboard_valid_sprint AS s
      ON s.sprint_id = bs.sprint_id
    WHERE bs.assignment_status IN ('atribuido', 'ambiguo')
    GROUP BY bs.entry_id, bs.sprint_id
)
SELECT
    e.entry_id,
    e.entry_date,
    e.duration_hours,
    e.user_id,
    e.collaborator_name,
    e.papel,
    e.collaborator_squad_id,
    e.collaborator_squad_name,
    e.has_focus_activity,
    e.has_focus_eligible_activity,
    e.has_main_activity,
    e.has_support_delivery_activity,
    e.has_delivery_activity,
    e.has_ticket,
    s.sprint_id,
    s.sprint_name,
    s.sprint_start,
    s.sprint_end,
    s.sprint_state,
    sl.assignment_status,
    sl.assignment_reason
FROM public.vw_dashboard_entry_final AS e
JOIN sprint_link AS sl ON sl.entry_id = e.entry_id
JOIN public.vw_dashboard_valid_sprint AS s ON s.sprint_id = sl.sprint_id;

COMMENT ON VIEW public.vw_dashboard_entry_sprint IS
    'Grão: lançamento × Sprint candidata do relacionamento Jira/Clockify. A atribuição oficial para métricas é vw_dashboard_entry_final.';

CREATE VIEW public.vw_dashboard_sprint_productivity AS
WITH entry_period AS (
    SELECT
        s.sprint_id AS period_sprint_id,
        s.sprint_name AS period_sprint_name,
        s.sprint_start AS period_sprint_start,
        s.sprint_end AS period_sprint_end,
        s.sprint_state AS period_sprint_state,
        e.entry_id,
        e.entry_date_local,
        e.duration_hours,
        e.user_id,
        e.collaborator_name,
        e.papel,
        e.collaborator_squad_id,
        e.collaborator_squad_name,
        e.has_ticket,
        e.has_tag,
        e.has_focus_activity,
        e.has_focus_eligible_activity,
        e.has_main_activity,
        e.has_support_delivery_activity,
        e.has_delivery_activity,
        e.has_sprint,
        e.sprint_assignment_status,
        e.sprint_id AS assigned_sprint_id
    FROM public.vw_dashboard_valid_sprint AS s
    JOIN public.vw_dashboard_entry_final AS e
      ON e.started_at IS NOT NULL
     AND e.ended_at IS NOT NULL
     AND e.ended_at > s.sprint_start
     AND (s.sprint_end IS NULL OR e.started_at < s.sprint_end)
)
SELECT
    ep.period_sprint_id AS sprint_id,
    ep.period_sprint_name AS sprint_name,
    ep.period_sprint_start AS sprint_start,
    ep.period_sprint_end AS sprint_end,
    ep.period_sprint_state AS sprint_state,
    ep.user_id,
    ep.collaborator_name,
    ep.papel,
    ep.collaborator_squad_id,
    ep.collaborator_squad_name,
    COUNT(*) AS lancamentos_total,
    COUNT(*) FILTER (WHERE ep.has_ticket) AS lancamentos_com_ticket,
    COUNT(*) FILTER (WHERE NOT ep.has_ticket) AS lancamentos_sem_ticket,
    SUM(ep.duration_hours) AS horas_totais,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE ep.has_ticket), 0.0) AS horas_com_ticket,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE NOT ep.has_ticket), 0.0) AS horas_sem_ticket,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE ep.has_focus_activity), 0.0) AS horas_foco,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE ep.has_focus_eligible_activity), 0.0) AS horas_foco_elegiveis,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE ep.has_main_activity), 0.0) AS horas_atividade_principal,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE ep.has_support_delivery_activity), 0.0) AS horas_apoio_entrega,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE ep.has_delivery_activity), 0.0) AS horas_de_entrega,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE NOT ep.has_tag), 0.0) AS horas_sem_tag,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE ep.has_ticket), 0.0)
        / NULLIF(SUM(ep.duration_hours), 0.0) AS indice_qualidade_lancamentos,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE ep.has_focus_activity), 0.0)
        / NULLIF(SUM(ep.duration_hours) FILTER (WHERE ep.has_focus_eligible_activity), 0.0)
        AS percentual_foco,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE ep.has_main_activity), 0.0)
        / NULLIF(SUM(ep.duration_hours), 0.0) AS percentual_atividade_principal,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE ep.has_support_delivery_activity), 0.0)
        / NULLIF(SUM(ep.duration_hours) FILTER (WHERE ep.has_delivery_activity), 0.0)
        AS indice_apoio_entrega,
    COALESCE(SUM(ep.duration_hours) FILTER (
        WHERE ep.assigned_sprint_id = ep.period_sprint_id
          AND ep.sprint_assignment_status = 'atribuido'
    ), 0.0) AS horas_vinculadas_sprint,
    COALESCE(SUM(ep.duration_hours) FILTER (
        WHERE ep.assigned_sprint_id = ep.period_sprint_id
          AND ep.sprint_assignment_status = 'atribuido'
    ), 0.0) / NULLIF(SUM(ep.duration_hours), 0.0)
        AS percentual_horas_vinculadas_sprint,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE ep.sprint_assignment_status = 'sem_sprint'), 0.0)
        AS horas_sem_sprint,
    COALESCE(SUM(ep.duration_hours) FILTER (WHERE ep.sprint_assignment_status = 'ambiguo'), 0.0)
        AS horas_sprint_ambiguas
FROM entry_period AS ep
GROUP BY
    ep.period_sprint_id, ep.period_sprint_name, ep.period_sprint_start,
    ep.period_sprint_end, ep.period_sprint_state, ep.user_id,
    ep.collaborator_name, ep.papel, ep.collaborator_squad_id,
    ep.collaborator_squad_name;

COMMENT ON VIEW public.vw_dashboard_sprint_productivity IS
    'Grão: Sprint pelo intervalo de datas × colaborador. A fonte de lançamentos é sempre vw_dashboard_entry_final.';

CREATE VIEW public.vw_dashboard_sprint_kpis AS
WITH ticket_kpis AS (
    SELECT
        sprint_id,
        COUNT(DISTINCT issue_key) AS tickets_total,
        COUNT(DISTINCT issue_key) FILTER (WHERE status_agrupado = 'Concluído') AS tickets_concluidos,
        COUNT(DISTINCT issue_key) FILTER (WHERE planejamento_status = 'planejado') AS tickets_planejados_inicio,
        COUNT(DISTINCT issue_key) FILTER (
            WHERE planejamento_status = 'planejado' AND status_agrupado = 'Concluído'
        ) AS tickets_planejados_concluidos,
        COUNT(DISTINCT issue_key) FILTER (WHERE status_agrupado <> 'Concluído') AS tickets_nao_concluidos,
        COUNT(DISTINCT issue_key) FILTER (WHERE planejamento_status = 'atravessado') AS tickets_atravessados,
        AVG(resolution_time_days) FILTER (
            WHERE status_agrupado = 'Concluído' AND resolution_time_days IS NOT NULL
        ) AS tmr_medio_dias,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_time_days) FILTER (
            WHERE status_agrupado = 'Concluído' AND resolution_time_days IS NOT NULL
        ) AS tmr_mediano_dias,
        COUNT(DISTINCT issue_key) FILTER (
            WHERE status_agrupado = 'Concluído' AND resolution_time_days IS NOT NULL
        ) AS tmr_tickets_validos,
        COALESCE(SUM(original_estimate_hours), 0.0) AS horas_estimadas
    FROM public.vw_dashboard_ticket_sprint
    WHERE planejamento_status IN ('planejado', 'atravessado')
    GROUP BY sprint_id
), assigned_clockify AS (
    SELECT
        e.sprint_id,
        SUM(e.duration_hours) AS horas_total,
        SUM(e.duration_hours) FILTER (WHERE e.has_focus_activity) AS horas_foco,
        SUM(e.duration_hours) FILTER (WHERE e.has_focus_eligible_activity) AS horas_foco_elegiveis,
        SUM(e.duration_hours) FILTER (WHERE e.has_main_activity) AS horas_atividade_principal,
        SUM(e.duration_hours) FILTER (WHERE e.has_support_delivery_activity) AS horas_apoio_entrega,
        SUM(e.duration_hours) FILTER (WHERE e.has_delivery_activity) AS horas_de_entrega,
        SUM(e.duration_hours) FILTER (WHERE NOT e.has_tag) AS horas_sem_tag,
        SUM(e.duration_hours) FILTER (WHERE NOT e.has_ticket) AS horas_sem_ticket
    FROM public.vw_dashboard_entry_final AS e
    WHERE e.sprint_id IS NOT NULL
      AND e.sprint_assignment_status = 'atribuido'
    GROUP BY e.sprint_id
), ambiguous_clockify AS (
    SELECT
        es.sprint_id,
        SUM(e.duration_hours) AS horas_ambiguas
    FROM public.vw_dashboard_entry_sprint AS es
    JOIN public.vw_dashboard_entry_final AS e ON e.entry_id = es.entry_id
    WHERE es.assignment_status = 'ambiguo'
    GROUP BY es.sprint_id
)
SELECT
    s.sprint_id, s.sprint_name, s.sprint_start, s.sprint_end, s.sprint_state,
    COALESCE(tk.tickets_total, 0) AS tickets_total,
    COALESCE(tk.tickets_concluidos, 0) AS tickets_concluidos,
    COALESCE(tk.tickets_planejados_inicio, 0) AS tickets_planejados_inicio,
    COALESCE(tk.tickets_planejados_concluidos, 0) AS tickets_planejados_concluidos,
    COALESCE(tk.tickets_nao_concluidos, 0) AS tickets_nao_concluidos,
    COALESCE(tk.tickets_atravessados, 0) AS tickets_atravessados,
    tk.tickets_planejados_concluidos::numeric / NULLIF(tk.tickets_planejados_inicio, 0)
        AS eficiencia_sprint,
    tk.tickets_atravessados::numeric / NULLIF(tk.tickets_total, 0)
        AS percentual_atravessamento,
    tk.tmr_medio_dias, tk.tmr_mediano_dias, tk.tmr_tickets_validos,
    COALESCE(tk.horas_estimadas, 0.0) AS horas_estimadas,
    COALESCE(ac.horas_total, 0.0) AS horas_total,
    COALESCE(ac.horas_foco, 0.0) AS horas_foco,
    COALESCE(ac.horas_foco_elegiveis, 0.0) AS horas_foco_elegiveis,
    COALESCE(ac.horas_atividade_principal, 0.0) AS horas_atividade_principal,
    COALESCE(ac.horas_apoio_entrega, 0.0) AS horas_apoio_entrega,
    COALESCE(ac.horas_de_entrega, 0.0) AS horas_de_entrega,
    COALESCE(ac.horas_sem_tag, 0.0) AS horas_sem_tag,
    COALESCE(ac.horas_sem_ticket, 0.0) AS horas_sem_ticket,
    COALESCE(amb.horas_ambiguas, 0.0) AS horas_ambiguas,
    ac.horas_foco / NULLIF(ac.horas_foco_elegiveis, 0.0) AS percentual_foco,
    ac.horas_atividade_principal / NULLIF(ac.horas_total, 0.0)
        AS percentual_atividade_principal,
    ac.horas_apoio_entrega / NULLIF(ac.horas_de_entrega, 0.0)
        AS indice_apoio_entrega,
    ac.horas_total / NULLIF(tk.tickets_concluidos, 0) AS horas_por_ticket_concluido
FROM public.vw_dashboard_valid_sprint AS s
LEFT JOIN ticket_kpis AS tk ON tk.sprint_id = s.sprint_id
LEFT JOIN assigned_clockify AS ac ON ac.sprint_id = s.sprint_id
LEFT JOIN ambiguous_clockify AS amb ON amb.sprint_id = s.sprint_id;

COMMENT ON VIEW public.vw_dashboard_sprint_kpis IS
    'Resumo por Sprint. Horas Clockify e indicadores de foco usam exclusivamente vw_dashboard_entry_final; tickets usam vw_dashboard_ticket_sprint.';
"""


GRANTS_SQL = """
DO $grant_dashboard_contract$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'produtividade_reader') THEN
        GRANT USAGE ON SCHEMA public TO produtividade_reader;
        GRANT SELECT ON
            public.dim_papel_atividade_principal,
            public.vw_dashboard_entry_final,
            public.vw_dashboard_entry_sprint,
            public.vw_dashboard_entry_tag,
            public.vw_dashboard_filter_sprint_squad,
            public.vw_dashboard_sprint_window,
            public.vw_dashboard_sprint_kpis,
            public.vw_dashboard_sprint_productivity,
            public.vw_dashboard_sprint_squad,
            public.vw_dashboard_ticket_filter_bridge,
            public.vw_dashboard_ticket_filterable,
            public.vw_dashboard_ticket_sprint,
            public.vw_dashboard_valid_sprint,
            public.vw_conferencia_horas_dia,
            public.vw_conferencia_horas_semana,
            public.vw_fila_revisao_horas,
            public.vw_flow_marcacao_detail,
            public.vw_flow_ponto_dia
        TO produtividade_reader;

        REVOKE SELECT ON
            public.vw_dashboard_entry_base,
            public.vw_clockify_entry_detail,
            public.vw_clockify_entry_tag_detail,
            public.vw_clockify_entry_sprint_detail,
            public.vw_clockify_entry_issue_detail,
            public.vw_jira_ticket_sprint_detail
        FROM produtividade_reader;
        REVOKE SELECT ON TABLE
            public.dim_calendario,
            public.fato_sprint_capacidade
        FROM produtividade_reader;
    END IF;
END
$grant_dashboard_contract$;

COMMENT ON VIEW public.vw_dashboard_entry_base IS
    'DEPRECATED: compatibilidade temporária. Não usar no dashboard; a fonte oficial é vw_dashboard_entry_final. Remoção prevista na segunda rodada de limpeza.';
COMMENT ON VIEW public.vw_jira_ticket_sprint_detail IS
    'DEPRECATED: fonte legada de ticket × sprint. Usar vw_dashboard_ticket_sprint; remoção prevista na segunda rodada de limpeza.';
COMMENT ON VIEW public.vw_clockify_entry_detail IS
    'DEPRECATED: view Clockify legada; o dashboard deve usar vw_dashboard_entry_final.';
COMMENT ON VIEW public.vw_clockify_entry_tag_detail IS
    'DEPRECATED: view Clockify legada; o dashboard deve usar vw_dashboard_entry_tag.';
COMMENT ON VIEW public.vw_clockify_entry_sprint_detail IS
    'DEPRECATED: view Clockify legada; o dashboard deve usar vw_dashboard_entry_sprint.';
COMMENT ON VIEW public.vw_clockify_entry_issue_detail IS
    'DEPRECATED: view Clockify legada; usar as views oficiais de ticket do dashboard.';
COMMENT ON TABLE public.dim_calendario IS
    'DEPRECATED: não participa da camada dinâmica de capacidade. Remoção prevista na segunda rodada de limpeza.';
COMMENT ON TABLE public.fato_sprint_capacidade IS
    'DEPRECATED: snapshot histórico inconsistente não é mais fonte de runtime. A capacidade oficial é dinâmica, derivada de Sprint × Squad × grupo de capacidade atual. Remoção prevista após validação da fase 25.';
COMMENT ON TABLE public.etl_view_version IS
    'DEPRECATED: controle legado de versão de views. A versão unificada é etl_schema_version.';
"""


def ensure_phase25_schema(engine: Engine) -> None:
    """Install the canonical entry contract and the unified grants."""
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '30s'"))
        connection.execute(text("SET LOCAL statement_timeout = '5min'"))
        connection.exec_driver_sql(SPRINT_WINDOW_VIEW_SQL)
        connection.exec_driver_sql(CANONICAL_ENTRY_CONTRACT_SQL)
        connection.exec_driver_sql(GRANTS_SQL)
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE25_VERSION},
        )
