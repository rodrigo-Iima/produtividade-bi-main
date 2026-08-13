"""Create the grain-safe productivity dashboard sources.

Phase 26 adds views consumed by the new Analytics Interno contracts. Every
view has an explicit grain and avoids using expanded ticket/tag/Flow sources
as additive facts.
"""

from sqlalchemy import Engine, text


PHASE26_VERSION = 26


PRODUCTIVITY_CONTRACT_VIEWS_SQL = """
DROP VIEW IF EXISTS
    public.vw_dashboard_data_freshness,
    public.vw_dashboard_sprint_timebox_detail,
    public.vw_dashboard_ticket_actual_hours,
    public.vw_dashboard_entry_tag_metrics
CASCADE;

CREATE VIEW public.vw_dashboard_entry_tag_metrics AS
WITH tag_counts AS (
    SELECT
        entry_id,
        COUNT(*) AS valid_tag_count
    FROM public.vw_dashboard_entry_tag
    GROUP BY entry_id
)
SELECT
    et.entry_id,
    et.entry_date,
    et.duration_hours AS duration_hours_original,
    et.user_id,
    et.collaborator_name,
    et.papel,
    et.collaborator_squad_id,
    et.collaborator_squad_name,
    et.sprint_id,
    et.sprint_name,
    et.sprint_start,
    et.sprint_end,
    et.sprint_state,
    et.sprint_assignment_status,
    et.tag_id,
    et.tag_name,
    et.tag_name_normalized,
    et.foco_flag,
    et.foco_flag_dentro,
    tc.valid_tag_count,
    et.duration_hours / NULLIF(tc.valid_tag_count, 0)
        AS allocated_duration_hours
FROM public.vw_dashboard_entry_tag AS et
JOIN tag_counts AS tc
  ON tc.entry_id = et.entry_id;

COMMENT ON VIEW public.vw_dashboard_entry_tag_metrics IS
    'Grão: lançamento × tag. allocated_duration_hours divide a duração igualmente entre as tags válidas e reconcilia com a duração original da entrada.';

CREATE VIEW public.vw_dashboard_ticket_actual_hours AS
WITH entry_issue_sprint AS (
    SELECT
        bi.entry_id,
        bi.issue_key,
        ts.sprint_id,
        ts.sprint_name,
        ts.sprint_state,
        ts.issue_type_name,
        ts.jira_squad_id,
        ts.jira_squad_name,
        ts.status_original,
        ts.status_agrupado,
        ts.planejado_no_inicio,
        ts.planejamento_status,
        e.user_id,
        ef.collaborator_name,
        ef.papel,
        ef.collaborator_squad_id,
        ef.collaborator_squad_name,
        e.entry_date_local,
        e.duration_seconds / 3600.0 AS duration_hours,
        COUNT(*) OVER (PARTITION BY bi.entry_id) AS linked_issue_count
    FROM public.bridge_clockify_entry_issue AS bi
    JOIN public.fato_clockify_entry AS e
      ON e.entry_id = bi.entry_id
    JOIN public.vw_dashboard_entry_final AS ef
      ON ef.entry_id = e.entry_id
     AND ef.sprint_assignment_status = 'atribuido'
    JOIN public.vw_dashboard_ticket_sprint AS ts
      ON ts.issue_key = bi.issue_key
     AND ts.sprint_id = ef.sprint_id
), dev_hours_by_entry AS (
    SELECT
        entry_id,
        COALESCE(
            SUM(allocated_duration_hours)
                FILTER (WHERE tag_name_normalized = 'dev'),
            0.0
        ) AS dev_hours
    FROM public.vw_dashboard_entry_tag_metrics
    GROUP BY entry_id
)
SELECT
    eis.issue_key,
    eis.sprint_id,
    eis.sprint_name,
    eis.sprint_state,
    eis.issue_type_name,
    eis.jira_squad_id,
    eis.jira_squad_name,
    eis.status_original,
    eis.status_agrupado,
    eis.planejado_no_inicio,
    eis.planejamento_status,
    eis.user_id,
    eis.collaborator_name,
    eis.papel,
    eis.collaborator_squad_id,
    eis.collaborator_squad_name,
    COUNT(DISTINCT eis.entry_id) AS linked_entry_count,
    MIN(eis.entry_date_local) AS first_entry_date,
    MAX(eis.entry_date_local) AS last_entry_date,
    SUM(eis.duration_hours / NULLIF(eis.linked_issue_count, 0))
        AS actual_hours,
    SUM(COALESCE(dev.dev_hours, 0.0) / NULLIF(eis.linked_issue_count, 0))
        AS dev_hours
FROM entry_issue_sprint AS eis
LEFT JOIN dev_hours_by_entry AS dev
  ON dev.entry_id = eis.entry_id
GROUP BY
    eis.issue_key,
    eis.sprint_id,
    eis.sprint_name,
    eis.sprint_state,
    eis.issue_type_name,
    eis.jira_squad_id,
    eis.jira_squad_name,
    eis.status_original,
    eis.status_agrupado,
    eis.planejado_no_inicio,
    eis.planejamento_status,
    eis.user_id,
    eis.collaborator_name,
    eis.papel,
    eis.collaborator_squad_id,
    eis.collaborator_squad_name;

COMMENT ON VIEW public.vw_dashboard_ticket_actual_hours IS
    'Grão: ticket × Sprint × colaborador. Horas de uma entrada ligada a múltiplos tickets são divididas igualmente entre os tickets válidos da mesma Sprint; estimativas não são repetidas nesta view.';

CREATE VIEW public.vw_dashboard_sprint_timebox_detail AS
WITH daily_reconciliation AS (
    SELECT
        c.sprint_id,
        c.user_id,
        COALESCE(SUM(d.point_worked_hours), 0.0) AS hours_worked,
        COUNT(d.work_date) FILTER (
            WHERE d.flow_covered IS TRUE
        ) AS flow_observed_days,
        COUNT(d.work_date) FILTER (
            WHERE d.flow_covered IS TRUE
              AND d.point_mark_count > 0
        ) AS flow_marked_days,
        COUNT(d.work_date) FILTER (
            WHERE d.flow_covered IS TRUE
              AND LOWER(BTRIM(COALESCE(d.flow_day_kind, ''))) IN (
                  'compensado',
                  'compensated',
                  'férias',
                  'ferias',
                  'repouso remunerado',
                  'ocorrência',
                  'ocorrencia'
              )
        ) AS flow_non_working_days,
        COUNT(d.work_date) FILTER (
            WHERE d.flow_covered IS TRUE
              AND LOWER(BTRIM(COALESCE(d.flow_day_kind, ''))) NOT IN (
                  'compensado',
                  'compensated',
                  'férias',
                  'ferias',
                  'repouso remunerado',
                  'ocorrência',
                  'ocorrencia'
              )
        ) AS eligible_flow_days,
        COUNT(d.work_date) FILTER (
            WHERE d.flow_covered IS TRUE
              AND LOWER(BTRIM(COALESCE(d.flow_day_kind, ''))) NOT IN (
                  'compensado',
                  'compensated',
                  'férias',
                  'ferias',
                  'repouso remunerado',
                  'ocorrência',
                  'ocorrencia'
              )
              AND d.meets_clockify_utilization_target IS TRUE
        ) AS logging_complete_days,
        MAX(d.calculated_at) AS reconciliation_calculated_at
    FROM public.vw_dashboard_sprint_capacity_detail AS c
    LEFT JOIN public.vw_conferencia_horas_dia AS d
      ON d.user_id = c.user_id
     AND d.work_date >= (
         c.sprint_start AT TIME ZONE 'America/Sao_Paulo'
     )::DATE
     AND d.work_date < c.effective_sprint_end_date
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
    c.snapshot_business_days,
    c.flow_observed_business_days,
    c.flow_non_working_days,
    c.flow_non_working_days_applied,
    c.business_days,
    c.calendar_capacity_hours,
    c.flow_non_working_hours,
    c.capacity_hours,
    c.snapshot_capacity_hours,
    c.capacity_source,
    c.entry_count,
    c.entries_with_ticket,
    c.hours_logged,
    c.hours_with_ticket,
    c.hours_without_ticket,
    c.hours_focus,
    c.hours_main_activity,
    c.hours_support_delivery,
    COALESCE(d.hours_worked, 0.0) AS hours_worked,
    COALESCE(d.flow_observed_days, 0) AS flow_observed_days,
    COALESCE(d.flow_marked_days, 0) AS flow_marked_days,
    COALESCE(d.eligible_flow_days, 0) AS eligible_flow_days,
    COALESCE(d.logging_complete_days, 0) AS logging_complete_days,
    GREATEST(c.capacity_hours - c.hours_logged, 0.0)
        AS logging_gap_hours,
    GREATEST(COALESCE(d.hours_worked, 0.0) - c.capacity_hours, 0.0)
        AS overtime_hours,
    CASE
        WHEN c.business_days > 0
        THEN 100.0 * COALESCE(d.flow_observed_days, 0)
            / c.business_days
    END AS flow_coverage_pct,
    CASE
        WHEN COALESCE(d.eligible_flow_days, 0) > 0
        THEN 100.0 * d.logging_complete_days
            / d.eligible_flow_days
    END AS logging_compliance_pct,
    GREATEST(
        c.calculated_at,
        COALESCE(d.reconciliation_calculated_at, c.calculated_at)
    ) AS calculated_at
FROM public.vw_dashboard_sprint_capacity_detail AS c
LEFT JOIN daily_reconciliation AS d
  ON d.sprint_id = c.sprint_id
 AND d.user_id = c.user_id;

COMMENT ON VIEW public.vw_dashboard_sprint_timebox_detail IS
    'Grão: Sprint × colaborador. Capacidade vem da view dinâmica; horas trabalhadas e conformidade vêm da conferência diária única por usuário/data; gap e hora extra são calculados individualmente antes da agregação.';

CREATE VIEW public.vw_dashboard_data_freshness AS
WITH source_steps(source, step_name) AS (
    VALUES
        ('JIRA', 'Extração e carga do Jira'),
        ('JIRA', 'Extração do changelog de sprint'),
        ('JIRA', 'Enriquecimento das sprints Jira'),
        ('JIRA', 'Mapeamento Sprint × Squad pelos quick filters Jira'),
        ('CLOCKIFY', 'Extração e carga do Clockify'),
        ('FLOW', 'Sincronização de colaboradores Flow'),
        ('FLOW', 'Extração e carga das marcações Flow'),
        ('FLOW', 'Conferência diária Flow × Clockify')
), run_status AS (
    SELECT
        ss.source,
        MAX(l.finished_at) FILTER (WHERE l.status = 'success')
            AS last_success_at,
        MAX(l.finished_at) FILTER (WHERE l.status = 'failed')
            AS last_failure_at
    FROM source_steps AS ss
    LEFT JOIN public.etl_run_log AS l
      ON l.step_name = ss.step_name
    GROUP BY ss.source
), source_records(source, last_record_at, record_count) AS (
    SELECT
        'JIRA',
        MAX(updated_at),
        COUNT(*)
    FROM public.vw_dashboard_ticket_sprint
    UNION ALL
    SELECT
        'CLOCKIFY',
        MAX(started_at),
        COUNT(*)
    FROM public.vw_dashboard_entry_final
    UNION ALL
    SELECT
        'FLOW',
        MAX(calculated_at),
        COUNT(*)
    FROM public.vw_conferencia_horas_dia
)
SELECT
    sr.source,
    rs.last_success_at,
    sr.last_record_at,
    rs.last_failure_at,
    CASE
        WHEN rs.last_success_at IS NULL THEN 'unavailable'
        WHEN rs.last_failure_at IS NOT NULL
         AND rs.last_failure_at > rs.last_success_at THEN 'failed'
        ELSE 'available'
    END AS status,
    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - sr.last_record_at))
        / 60.0 AS delay_minutes,
    sr.record_count
FROM source_records AS sr
LEFT JOIN run_status AS rs
  ON rs.source = sr.source;

COMMENT ON VIEW public.vw_dashboard_data_freshness IS
    'Grão: uma linha por fonte Jira, Clockify ou Flow. Não expõe etl_run_log; o BFF aplica o limite de freshness e converte status em FRESH, STALE, PARTIAL ou UNAVAILABLE.';

DO $grant_productivity_contract_views$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'produtividade_reader'
    ) THEN
        GRANT SELECT ON
            public.vw_dashboard_entry_tag_metrics,
            public.vw_dashboard_ticket_actual_hours,
            public.vw_dashboard_sprint_timebox_detail,
            public.vw_dashboard_data_freshness
        TO produtividade_reader;
    END IF;
END
$grant_productivity_contract_views$;
"""


def ensure_phase26_schema(engine: Engine) -> None:
    """Install the grain-safe productivity dashboard contract views."""
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '30s'"))
        connection.execute(text("SET LOCAL statement_timeout = '5min'"))
        connection.execute(text(PRODUCTIVITY_CONTRACT_VIEWS_SQL))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE26_VERSION},
        )
