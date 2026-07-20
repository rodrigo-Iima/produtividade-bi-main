-- Migration da camada analítica do dashboard Gestão à Vista
-- Projeto Produtividade | PostgreSQL | America/Sao_Paulo
--
-- Esta migration deve ser aplicada com psql por uma conta com permissão de DDL.
-- Ela recria as views analíticas dentro de uma transação para permitir evolução
-- de colunas e dependências sem depender de CREATE OR REPLACE VIEW compatível.
--
-- Princípios de grão:
--   vw_dashboard_valid_sprint: uma linha por sprint válida
--   vw_dashboard_entry_base: uma linha por lançamento Clockify
--   vw_dashboard_sprint_productivity: uma linha por sprint de período x colaborador
--   vw_dashboard_entry_tag: uma linha por lançamento x tag
--   vw_dashboard_entry_sprint: uma linha por lançamento x sprint candidata
--   vw_dashboard_ticket_sprint: uma linha por ticket x sprint
--   vw_dashboard_ticket_filter_bridge: ticket x sprint x colaborador relacionado
--   vw_dashboard_ticket_filterable: ticket x sprint x colaborador, com atributos
--   vw_dashboard_sprint_kpis: resumo não filtrado, uma linha por sprint
--
-- Regra de sprint analítica:
--   sprint_start > 01/01/2026, sprint_start <= momento atual e estado active/closed.

BEGIN;

-- Pré-requisito do dashboard. Mantém esta migration executável isoladamente
-- em ambientes que ainda não receberam a migration Python da fase 5.
ALTER TABLE public.dim_ticket_jira
    ADD COLUMN IF NOT EXISTS atravessamento_flag BOOLEAN;

CREATE INDEX IF NOT EXISTS ix_dim_ticket_jira_atravessamento_flag
    ON public.dim_ticket_jira (atravessamento_flag);

DROP VIEW IF EXISTS
    public.vw_dashboard_sprint_kpis,
    public.vw_dashboard_ticket_filterable,
    public.vw_dashboard_ticket_filter_bridge,
    public.vw_dashboard_ticket_sprint,
    public.vw_dashboard_sprint_productivity,
    public.vw_dashboard_entry_sprint,
    public.vw_dashboard_entry_tag,
    public.vw_dashboard_entry_base,
    public.vw_dashboard_valid_sprint,
    public.dim_papel_atividade_principal
CASCADE;

CREATE VIEW public.dim_papel_atividade_principal AS
SELECT
    v.papel,
    t.tag_id,
    t.nome AS tag_name,
    t.nome_normalizado AS tag_name_normalized,
    'mapping_inicial'::text AS mapping_source
FROM (
    VALUES
        ('Desenvolvedor'::text, 'dev'::text),
        ('Analista de dados'::text, 'analise e levantamento de requisitos'::text),
        ('Analista de requisitos'::text, 'analise e levantamento de requisitos'::text)
) AS v(papel, tag_name_normalized)
JOIN public.dim_tag AS t
  ON t.nome_normalizado = v.tag_name_normalized;

COMMENT ON VIEW public.dim_papel_atividade_principal IS
    'Mapeamento de papel para atividade principal. A ausência de mapeamento não classifica a hora como atividade principal.';

CREATE VIEW public.vw_dashboard_valid_sprint AS
SELECT
    s.sprint_id,
    s.sprint_name,
    s.sprint_start,
    s.sprint_end,
    LOWER(s.sprint_state) AS sprint_state
FROM public.dim_sprint AS s
WHERE s.sprint_start > (
          TIMESTAMP '2026-01-01 00:00:00'
          AT TIME ZONE 'America/Sao_Paulo'
      )
  AND s.sprint_start <= CURRENT_TIMESTAMP
  AND LOWER(s.sprint_state) IN ('active', 'closed');

COMMENT ON VIEW public.vw_dashboard_valid_sprint IS
    'Sprints iniciadas estritamente depois de 01/01/2026 e até o momento atual, somente active/closed.';

CREATE VIEW public.vw_dashboard_entry_base AS
WITH tag_by_entry AS (
    SELECT
        e.entry_id,
        COUNT(bt.tag_id) > 0 AS has_tag,
        COALESCE(
            BOOL_OR(bt.foco_flag = 'Dentro do Foco'),
            FALSE
        ) AS has_focus_activity,
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
            BOOL_OR(
                t.nome_normalizado IN (
                    'dev',
                    'qa',
                    'dev-check',
                    'analise e levantamento de requisitos'
                )
            ),
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
      ON pm.papel = c.papel
    GROUP BY e.entry_id
),
issue_by_entry AS (
    SELECT
        bi.entry_id,
        COUNT(DISTINCT bi.issue_key) > 0 AS has_ticket
    FROM public.bridge_clockify_entry_issue AS bi
    GROUP BY bi.entry_id
),
entry_sprint_candidates AS (
    SELECT
        bs.entry_id,
        bs.sprint_id,
        bs.assignment_status,
        bs.assignment_reason
    FROM public.bridge_clockify_entry_sprint AS bs
    JOIN public.vw_dashboard_valid_sprint AS s
      ON s.sprint_id = bs.sprint_id
    WHERE bs.assignment_status IN ('atribuido', 'ambiguo')
),
entry_sprint_rollup AS (
    SELECT
        c.entry_id,
        COUNT(DISTINCT c.sprint_id) AS sprint_candidate_count,
        CASE
            WHEN COUNT(DISTINCT c.sprint_id) = 1
             AND BOOL_OR(c.assignment_status = 'atribuido')
                THEN MIN(c.sprint_id)
            ELSE NULL
        END AS canonical_sprint_id,
        CASE
            WHEN COUNT(DISTINCT c.sprint_id) = 1
             AND BOOL_OR(c.assignment_status = 'atribuido')
                THEN 'atribuido'
            WHEN COUNT(DISTINCT c.sprint_id) > 1
                THEN 'ambiguo'
            ELSE 'sem_sprint'
        END AS canonical_assignment_status,
        MAX(c.assignment_reason) AS canonical_assignment_reason
    FROM entry_sprint_candidates AS c
    GROUP BY c.entry_id
)
SELECT
    e.entry_id,
    e.entry_date,
    e.started_at,
    e.ended_at,
    e.duration_seconds,
    e.duration_seconds / 3600.0 AS duration_hours,
    e.user_id,
    c.name AS collaborator_name,
    c.papel,
    c.squad_id AS collaborator_squad_id,
    sq.nome AS collaborator_squad_name,
    e.project_name,
    e.task_name,
    esr.canonical_sprint_id AS sprint_id,
    s.sprint_name,
    s.sprint_start,
    s.sprint_end,
    s.sprint_state,
    COALESCE(esr.sprint_candidate_count, 0) > 0 AS has_sprint,
    COALESCE(esr.canonical_assignment_status, 'sem_sprint') AS sprint_assignment_status,
    esr.canonical_assignment_reason AS sprint_assignment_reason,
    COALESCE(tf.has_tag, FALSE) AS has_tag,
    COALESCE(ifl.has_ticket, FALSE) AS has_ticket,
    COALESCE(tf.has_focus_activity, FALSE) AS has_focus_activity,
    COALESCE(tf.has_focus_eligible_activity, FALSE) AS has_focus_eligible_activity,
    COALESCE(tf.has_main_activity, FALSE) AS has_main_activity,
    COALESCE(tf.has_support_delivery_activity, FALSE) AS has_support_delivery_activity,
    COALESCE(tf.has_delivery_activity, FALSE) AS has_delivery_activity
FROM public.fato_clockify_entry AS e
LEFT JOIN public.dim_colaborador AS c
  ON c.user_id = e.user_id
LEFT JOIN public.dim_squad AS sq
  ON sq.squad_id = c.squad_id
LEFT JOIN tag_by_entry AS tf
  ON tf.entry_id = e.entry_id
LEFT JOIN issue_by_entry AS ifl
  ON ifl.entry_id = e.entry_id
LEFT JOIN entry_sprint_rollup AS esr
  ON esr.entry_id = e.entry_id
LEFT JOIN public.vw_dashboard_valid_sprint AS s
  ON s.sprint_id = esr.canonical_sprint_id;

COMMENT ON VIEW public.vw_dashboard_entry_base IS
    'Grão: uma linha por lançamento. O sprint_id só é preenchido para uma única atribuição válida; ambiguidades ficam sinalizadas sem duplicar horas.';

CREATE VIEW public.vw_dashboard_sprint_productivity AS
WITH entry_period AS (
    SELECT
        s.sprint_id AS period_sprint_id,
        s.sprint_name AS period_sprint_name,
        s.sprint_start AS period_sprint_start,
        s.sprint_end AS period_sprint_end,
        s.sprint_state AS period_sprint_state,
        eb.entry_id,
        eb.entry_date,
        eb.duration_hours,
        eb.user_id,
        eb.collaborator_name,
        eb.papel,
        eb.collaborator_squad_id,
        eb.collaborator_squad_name,
        eb.has_ticket,
        eb.has_tag,
        eb.has_focus_activity,
        eb.has_focus_eligible_activity,
        eb.has_main_activity,
        eb.has_support_delivery_activity,
        eb.has_delivery_activity,
        eb.has_sprint,
        eb.sprint_assignment_status,
        eb.sprint_id AS ticket_sprint_id
    FROM public.vw_dashboard_valid_sprint AS s
    JOIN public.vw_dashboard_entry_base AS eb
      ON eb.entry_date >= (
             s.sprint_start AT TIME ZONE 'America/Sao_Paulo'
         )::date
     AND eb.entry_date <= COALESCE(
             (s.sprint_end AT TIME ZONE 'America/Sao_Paulo')::date,
             CURRENT_DATE
         )
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
    COALESCE(
        SUM(ep.duration_hours) FILTER (WHERE ep.has_ticket),
        0.0
    ) AS horas_com_ticket,
    COALESCE(
        SUM(ep.duration_hours) FILTER (WHERE NOT ep.has_ticket),
        0.0
    ) AS horas_sem_ticket,
    COALESCE(
        SUM(ep.duration_hours) FILTER (WHERE ep.has_focus_activity),
        0.0
    ) AS horas_foco,
    COALESCE(
        SUM(ep.duration_hours) FILTER (
            WHERE ep.has_focus_eligible_activity
        ),
        0.0
    ) AS horas_foco_elegiveis,
    COALESCE(
        SUM(ep.duration_hours) FILTER (WHERE ep.has_main_activity),
        0.0
    ) AS horas_atividade_principal,
    COALESCE(
        SUM(ep.duration_hours) FILTER (
            WHERE ep.has_support_delivery_activity
        ),
        0.0
    ) AS horas_apoio_entrega,
    COALESCE(
        SUM(ep.duration_hours) FILTER (WHERE ep.has_delivery_activity),
        0.0
    ) AS horas_de_entrega,
    COALESCE(
        SUM(ep.duration_hours) FILTER (WHERE NOT ep.has_tag),
        0.0
    ) AS horas_sem_tag,
    COALESCE(
        SUM(ep.duration_hours) FILTER (WHERE ep.has_ticket),
        0.0
    ) / NULLIF(SUM(ep.duration_hours), 0.0)
        AS indice_qualidade_lancamentos,
    COALESCE(
        SUM(ep.duration_hours) FILTER (WHERE ep.has_focus_activity),
        0.0
    ) / NULLIF(
        SUM(ep.duration_hours) FILTER (
            WHERE ep.has_focus_eligible_activity
        ),
        0.0
    ) AS percentual_foco,
    COALESCE(
        SUM(ep.duration_hours) FILTER (WHERE ep.has_main_activity),
        0.0
    ) / NULLIF(SUM(ep.duration_hours), 0.0)
        AS percentual_atividade_principal,
    COALESCE(
        SUM(ep.duration_hours) FILTER (
            WHERE ep.has_support_delivery_activity
        ),
        0.0
    ) / NULLIF(
        SUM(ep.duration_hours) FILTER (
            WHERE ep.has_delivery_activity
        ),
        0.0
    ) AS indice_apoio_entrega,
    COALESCE(
        SUM(ep.duration_hours) FILTER (
            WHERE ep.ticket_sprint_id = ep.period_sprint_id
              AND ep.sprint_assignment_status = 'atribuido'
        ),
        0.0
    ) AS horas_vinculadas_sprint,
    COALESCE(
        SUM(ep.duration_hours) FILTER (
            WHERE ep.ticket_sprint_id = ep.period_sprint_id
              AND ep.sprint_assignment_status = 'atribuido'
        ),
        0.0
    ) / NULLIF(SUM(ep.duration_hours), 0.0)
        AS percentual_horas_vinculadas_sprint,
    COALESCE(
        SUM(ep.duration_hours) FILTER (
            WHERE ep.sprint_assignment_status = 'sem_sprint'
        ),
        0.0
    ) AS horas_sem_sprint,
    COALESCE(
        SUM(ep.duration_hours) FILTER (
            WHERE ep.sprint_assignment_status = 'ambiguo'
        ),
        0.0
    ) AS horas_sprint_ambiguas
FROM entry_period AS ep
GROUP BY
    ep.period_sprint_id,
    ep.period_sprint_name,
    ep.period_sprint_start,
    ep.period_sprint_end,
    ep.period_sprint_state,
    ep.user_id,
    ep.collaborator_name,
    ep.papel,
    ep.collaborator_squad_id,
    ep.collaborator_squad_name;

COMMENT ON VIEW public.vw_dashboard_sprint_productivity IS
    'Grão: sprint pelo período do calendário x colaborador. Horas totais, foco, atividade principal, apoio e qualidade são calculados sobre todos os lançamentos do período; o índice de qualidade é horas com ticket dividido por horas totais. Use esta view com filtro de sprint e recalcule os índices como razão das somas quando houver mais de um colaborador.';

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
    eb.entry_id,
    eb.entry_date,
    eb.duration_hours,
    eb.user_id,
    eb.collaborator_name,
    eb.papel,
    eb.collaborator_squad_id,
    eb.collaborator_squad_name,
    eb.sprint_id,
    eb.sprint_name,
    eb.sprint_start,
    eb.sprint_end,
    eb.sprint_state,
    eb.sprint_assignment_status,
    tl.tag_id,
    t.nome AS tag_name,
    t.nome_normalizado AS tag_name_normalized,
    tl.foco_flag,
    (tl.foco_flag = 'Dentro do Foco') AS foco_flag_dentro
FROM public.vw_dashboard_entry_base AS eb
JOIN tag_link AS tl
  ON tl.entry_id = eb.entry_id
JOIN public.dim_tag AS t
  ON t.tag_id = tl.tag_id;

COMMENT ON VIEW public.vw_dashboard_entry_tag IS
    'Grão: lançamento x tag. A mesma hora pode aparecer em mais de uma tag e não deve ser usada para o total geral.';

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
FROM public.vw_dashboard_entry_base AS e
JOIN sprint_link AS sl
  ON sl.entry_id = e.entry_id
JOIN public.vw_dashboard_valid_sprint AS s
  ON s.sprint_id = sl.sprint_id;

COMMENT ON VIEW public.vw_dashboard_entry_sprint IS
    'Grão: lançamento x sprint candidata. Cards padrão usam assignment_status = atribuido; ambiguidades ficam disponíveis para controle.';

CREATE VIEW public.vw_dashboard_ticket_sprint AS
WITH ticket_sprint_link AS (
    SELECT
        f.issue_key,
        f.sprint_id,
        MIN(f.sprint_entrada_at) AS sprint_entrada_at,
        BOOL_OR(f.planejado_no_inicio) AS planejado_no_inicio
    FROM public.fato_jira_ticket_sprint AS f
    JOIN public.vw_dashboard_valid_sprint AS s
      ON s.sprint_id = f.sprint_id
    GROUP BY f.issue_key, f.sprint_id
)
SELECT
    tsl.issue_key,
    tsl.sprint_id,
    s.sprint_name,
    s.sprint_start,
    s.sprint_end,
    s.sprint_state,
    t.summary,
    t.project_key,
    t.project_name,
    t.squad_jira,
    alias_jira.squad_id AS jira_squad_id,
    sq.nome AS jira_squad_name,
    t.status_original,
    COALESCE(st.status_agrupado, 'Não Classificado') AS status_agrupado,
    t.atravessamento_flag,
    t.created_at,
    t.resolved_at,
    t.updated_at,
    tsl.sprint_entrada_at,
    tsl.planejado_no_inicio,
    CASE
        WHEN t.created_at IS NOT NULL
         AND t.resolved_at IS NOT NULL
         AND t.resolved_at >= t.created_at
        THEN EXTRACT(EPOCH FROM (t.resolved_at - t.created_at)) / 3600.0
        ELSE NULL
    END AS resolution_time_hours,
    CASE
        WHEN t.created_at IS NOT NULL
         AND t.resolved_at IS NOT NULL
         AND t.resolved_at >= t.created_at
        THEN EXTRACT(EPOCH FROM (t.resolved_at - t.created_at)) / 86400.0
        ELSE NULL
    END AS resolution_time_days
FROM ticket_sprint_link AS tsl
JOIN public.vw_dashboard_valid_sprint AS s
  ON s.sprint_id = tsl.sprint_id
JOIN public.dim_ticket_jira AS t
  ON t.issue_key = tsl.issue_key
LEFT JOIN public.dim_status AS st
  ON st.status_original = t.status_original
LEFT JOIN public.dim_squad_alias AS alias_jira
  ON alias_jira.origem = 'jira'
 AND LOWER(TRIM(alias_jira.nome_bruto)) = LOWER(TRIM(t.squad_jira))
LEFT JOIN public.dim_squad AS sq
  ON sq.squad_id = alias_jira.squad_id;

COMMENT ON VIEW public.vw_dashboard_ticket_sprint IS
    'Grão: uma linha por ticket x sprint válida. TMR e contagens devem usar este grão ou uma deduplicação equivalente.';

CREATE VIEW public.vw_dashboard_ticket_filter_bridge AS
SELECT DISTINCT
    ts.issue_key,
    ts.sprint_id,
    c.user_id,
    c.name AS collaborator_name,
    c.papel,
    c.squad_id AS collaborator_squad_id,
    csq.nome AS collaborator_squad_name,
    ts.jira_squad_id,
    ts.jira_squad_name
FROM public.vw_dashboard_ticket_sprint AS ts
JOIN public.bridge_clockify_entry_issue AS bi
  ON bi.issue_key = ts.issue_key
JOIN public.fato_clockify_entry AS e
  ON e.entry_id = bi.entry_id
JOIN public.dim_colaborador AS c
  ON c.user_id = e.user_id
LEFT JOIN public.dim_squad AS csq
  ON csq.squad_id = c.squad_id;

COMMENT ON VIEW public.vw_dashboard_ticket_filter_bridge IS
    'Grão: ticket x sprint x colaborador relacionado. Squad Jira representa responsabilidade; squad colaborador representa quem apontou esforço.';

CREATE VIEW public.vw_dashboard_ticket_filterable AS
SELECT
    ts.issue_key,
    ts.sprint_id,
    ts.sprint_name,
    ts.sprint_start,
    ts.sprint_end,
    ts.sprint_state,
    ts.summary,
    ts.project_key,
    ts.project_name,
    ts.jira_squad_id,
    ts.jira_squad_name,
    ts.status_original,
    ts.status_agrupado,
    ts.atravessamento_flag,
    ts.created_at,
    ts.resolved_at,
    ts.updated_at,
    ts.sprint_entrada_at,
    ts.planejado_no_inicio,
    ts.resolution_time_hours,
    ts.resolution_time_days,
    b.user_id,
    b.collaborator_name,
    b.papel,
    b.collaborator_squad_id,
    b.collaborator_squad_name
FROM public.vw_dashboard_ticket_sprint AS ts
LEFT JOIN public.vw_dashboard_ticket_filter_bridge AS b
  ON b.issue_key = ts.issue_key
 AND b.sprint_id = ts.sprint_id;

COMMENT ON VIEW public.vw_dashboard_ticket_filterable IS
    'Grão: ticket x sprint x colaborador relacionado, com tickets sem Clockify preservados como linha nula. Use COUNT(DISTINCT issue_key) e deduplicação por ticket x sprint.';

CREATE VIEW public.vw_dashboard_sprint_kpis AS
WITH ticket_kpis AS (
    SELECT
        sprint_id,
        COUNT(DISTINCT issue_key) AS tickets_total,
        COUNT(DISTINCT issue_key) FILTER (
            WHERE status_agrupado = 'Concluído'
        ) AS tickets_concluidos,
        COUNT(DISTINCT issue_key) FILTER (
            WHERE planejado_no_inicio IS TRUE
        ) AS tickets_planejados_inicio,
        COUNT(DISTINCT issue_key) FILTER (
            WHERE planejado_no_inicio IS TRUE
              AND status_agrupado = 'Concluído'
        ) AS tickets_planejados_concluidos,
        COUNT(DISTINCT issue_key) FILTER (
            WHERE status_agrupado <> 'Concluído'
        ) AS tickets_nao_concluidos,
        COUNT(DISTINCT issue_key) FILTER (
            WHERE atravessamento_flag IS TRUE
        ) AS tickets_atravessados,
        AVG(resolution_time_days) FILTER (
            WHERE status_agrupado = 'Concluído'
              AND resolution_time_days IS NOT NULL
        ) AS tmr_medio_dias,
        percentile_cont(0.5) WITHIN GROUP (
            ORDER BY resolution_time_days
        ) FILTER (
            WHERE status_agrupado = 'Concluído'
              AND resolution_time_days IS NOT NULL
        ) AS tmr_mediano_dias,
        COUNT(DISTINCT issue_key) FILTER (
            WHERE status_agrupado = 'Concluído'
              AND resolution_time_days IS NOT NULL
        ) AS tmr_tickets_validos
    FROM public.vw_dashboard_ticket_sprint
    GROUP BY sprint_id
),
assigned_clockify AS (
    SELECT
        e.sprint_id,
        SUM(e.duration_hours) AS horas_total,
        SUM(e.duration_hours) FILTER (
            WHERE e.has_focus_activity
        ) AS horas_foco,
        SUM(e.duration_hours) FILTER (
            WHERE e.has_focus_eligible_activity
        ) AS horas_foco_elegiveis,
        SUM(e.duration_hours) FILTER (
            WHERE e.has_main_activity
        ) AS horas_atividade_principal,
        SUM(e.duration_hours) FILTER (
            WHERE e.has_support_delivery_activity
        ) AS horas_apoio_entrega,
        SUM(e.duration_hours) FILTER (
            WHERE e.has_delivery_activity
        ) AS horas_de_entrega,
        SUM(e.duration_hours) FILTER (
            WHERE NOT e.has_tag
        ) AS horas_sem_tag,
        SUM(e.duration_hours) FILTER (
            WHERE NOT e.has_ticket
        ) AS horas_sem_ticket
    FROM public.vw_dashboard_entry_base AS e
    WHERE e.sprint_id IS NOT NULL
      AND e.sprint_assignment_status = 'atribuido'
    GROUP BY e.sprint_id
),
ambiguous_clockify AS (
    SELECT
        es.sprint_id,
        SUM(e.duration_hours) AS horas_ambiguas
    FROM public.vw_dashboard_entry_sprint AS es
    JOIN public.vw_dashboard_entry_base AS e
      ON e.entry_id = es.entry_id
    WHERE es.assignment_status = 'ambiguo'
    GROUP BY es.sprint_id
)
SELECT
    s.sprint_id,
    s.sprint_name,
    s.sprint_start,
    s.sprint_end,
    s.sprint_state,
    COALESCE(tk.tickets_total, 0) AS tickets_total,
    COALESCE(tk.tickets_concluidos, 0) AS tickets_concluidos,
    COALESCE(tk.tickets_planejados_inicio, 0) AS tickets_planejados_inicio,
    COALESCE(tk.tickets_planejados_concluidos, 0) AS tickets_planejados_concluidos,
    COALESCE(tk.tickets_nao_concluidos, 0) AS tickets_nao_concluidos,
    COALESCE(tk.tickets_atravessados, 0) AS tickets_atravessados,
    tk.tickets_planejados_concluidos::numeric
        / NULLIF(tk.tickets_planejados_inicio, 0) AS eficiencia_sprint,
    tk.tickets_atravessados::numeric
        / NULLIF(tk.tickets_total, 0) AS percentual_atravessamento,
    tk.tmr_medio_dias,
    tk.tmr_mediano_dias,
    tk.tmr_tickets_validos,
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
    ac.horas_total / NULLIF(tk.tickets_concluidos, 0)
        AS horas_por_ticket_concluido
FROM public.vw_dashboard_valid_sprint AS s
LEFT JOIN ticket_kpis AS tk
  ON tk.sprint_id = s.sprint_id
LEFT JOIN assigned_clockify AS ac
  ON ac.sprint_id = s.sprint_id
LEFT JOIN ambiguous_clockify AS amb
  ON amb.sprint_id = s.sprint_id;

COMMENT ON VIEW public.vw_dashboard_sprint_kpis IS
    'Resumo não filtrado por pessoa. Para cards com Colaborador/Papel/Squad, usar as views filterable e agregações distintas.';

-- Índices de suporte às leituras analíticas.
CREATE INDEX IF NOT EXISTS ix_fato_clockify_entry_entry_date
    ON public.fato_clockify_entry (entry_date);
CREATE INDEX IF NOT EXISTS ix_fato_clockify_entry_user_id
    ON public.fato_clockify_entry (user_id);
CREATE INDEX IF NOT EXISTS ix_bridge_clockify_entry_tag_entry_id
    ON public.bridge_clockify_entry_tag (entry_id);
CREATE INDEX IF NOT EXISTS ix_bridge_clockify_entry_tag_tag_id
    ON public.bridge_clockify_entry_tag (tag_id);
CREATE INDEX IF NOT EXISTS ix_bridge_clockify_entry_sprint_entry_id
    ON public.bridge_clockify_entry_sprint (entry_id);
CREATE INDEX IF NOT EXISTS ix_bridge_clockify_entry_sprint_sprint_id
    ON public.bridge_clockify_entry_sprint (sprint_id);
CREATE INDEX IF NOT EXISTS ix_bridge_clockify_entry_issue_entry_id
    ON public.bridge_clockify_entry_issue (entry_id);
CREATE INDEX IF NOT EXISTS ix_bridge_clockify_entry_issue_issue_key
    ON public.bridge_clockify_entry_issue (issue_key);
CREATE INDEX IF NOT EXISTS ix_dim_colaborador_squad_id
    ON public.dim_colaborador (squad_id);
CREATE INDEX IF NOT EXISTS ix_dim_ticket_jira_squad_jira
    ON public.dim_ticket_jira (squad_jira);
CREATE INDEX IF NOT EXISTS ix_dim_ticket_jira_atravessamento_flag
    ON public.dim_ticket_jira (atravessamento_flag);
CREATE INDEX IF NOT EXISTS ix_fato_jira_ticket_sprint_issue_key
    ON public.fato_jira_ticket_sprint (issue_key);
CREATE INDEX IF NOT EXISTS ix_fato_jira_ticket_sprint_sprint_id
    ON public.fato_jira_ticket_sprint (sprint_id);
CREATE INDEX IF NOT EXISTS ix_dim_status_status_original
    ON public.dim_status (status_original);
CREATE INDEX IF NOT EXISTS ix_dim_squad_alias_origem_nome
    ON public.dim_squad_alias (origem, nome_bruto);

COMMIT;
