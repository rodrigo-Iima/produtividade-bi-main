"""Create the sprint-independent Jira project portfolio contract.

The views in this phase deliberately start from ``dim_ticket_jira`` and the
hierarchy bridge.  Sprint facts are not involved, so an Epic without a sprint
is still visible to the portfolio dashboard.
"""

from sqlalchemy import Engine, text


PHASE29_VERSION = 29


PROJECT_PORTFOLIO_VIEWS_SQL = r"""
DROP VIEW IF EXISTS
    public.vw_dashboard_project_freshness,
    public.vw_dashboard_project_portfolio,
    public.vw_dashboard_project_child
CASCADE;

CREATE VIEW public.vw_dashboard_project_child AS
WITH epic_scope AS (
    SELECT
        e.issue_key AS epic_issue_key,
        e.project_key
    FROM public.dim_ticket_jira AS e
    WHERE LOWER(TRIM(e.issue_type_name)) = 'epic'
      AND e.project_key IN ('ZGT', 'ZG', 'ZGTN', 'SRE')
      AND e.created_at >= TIMESTAMPTZ '2026-01-01 00:00:00+00'
      AND e.created_at < CURRENT_DATE + INTERVAL '1 day'
      AND e.source_present = TRUE
), direct_edges AS (
    SELECT DISTINCT ON (e.epic_issue_key, b.child_issue_key)
        e.epic_issue_key,
        b.child_issue_key,
        b.relationship_type,
        1 AS hierarchy_level
    FROM epic_scope AS e
    JOIN public.bridge_jira_issue_parent AS b
      ON b.parent_issue_key = e.epic_issue_key
     AND b.source_present = TRUE
    JOIN public.dim_ticket_jira AS child
      ON child.issue_key = b.child_issue_key
     AND child.source_present = TRUE
    ORDER BY
        e.epic_issue_key,
        b.child_issue_key,
        CASE WHEN b.relationship_type = 'parent' THEN 0 ELSE 1 END,
        b.last_seen_at DESC NULLS LAST
), descendant_edges AS (
    SELECT
        d.epic_issue_key,
        d.child_issue_key,
        d.relationship_type,
        d.hierarchy_level
    FROM direct_edges AS d

    UNION ALL

    SELECT
        d.epic_issue_key,
        b.child_issue_key,
        b.relationship_type,
        2 AS hierarchy_level
    FROM direct_edges AS d
    JOIN public.bridge_jira_issue_parent AS b
      ON b.parent_issue_key = d.child_issue_key
     AND b.source_present = TRUE
    JOIN public.dim_ticket_jira AS subtask
      ON subtask.issue_key = b.child_issue_key
     AND subtask.source_present = TRUE
     AND LOWER(TRIM(subtask.issue_type_name)) IN (
         'sub-task', 'subtask', 'sub task'
     )
), ticket_rows AS (
    SELECT DISTINCT ON (d.epic_issue_key, d.child_issue_key)
        d.epic_issue_key,
        d.child_issue_key AS issue_key,
        d.relationship_type,
        d.hierarchy_level,
        t.issue_type_name,
        t.summary,
        t.project_key,
        t.project_name,
        t.squad_jira,
        t.status_original,
        t.created_at,
        t.resolved_at,
        t.planned_start_date,
        t.due_date,
        t.original_estimate_seconds,
        t.original_estimate_seconds::NUMERIC / 3600.0
            AS original_estimate_hours,
        t.parent_issue_key,
        t.source_present,
        t.last_seen_at,
        CASE
            WHEN LOWER(TRIM(t.issue_type_name)) IN (
                'sub-task', 'subtask', 'sub task'
            ) OR d.hierarchy_level = 2
            THEN TRUE
            ELSE FALSE
        END AS is_subtask,
        COALESCE(mapping.status_name, t.status_original)
            AS status_mapping_name,
        COALESCE(mapping.status_group, legacy.status_agrupado)
            AS status_mapping_group,
        CASE
            WHEN COALESCE(mapping.starts_execution, FALSE)
              OR COALESCE(mapping.status_group, '') = 'execucao'
              OR LOWER(TRIM(t.status_original)) IN (
                  'aguardando início', 'aguardando inicio',
                  'em andamento', 'travado'
              )
            THEN 'active'
            WHEN COALESCE(mapping.is_completion, FALSE)
              OR COALESCE(mapping.status_group, '') = 'concluido'
              OR LOWER(TRIM(t.status_original)) IN (
                  'concluído', 'concluido', 'inválido', 'invalido',
                  'enviado para evolução', 'enviado para evolucao',
                  'showcase'
              )
              OR legacy.status_agrupado = 'Concluído'
            THEN 'completed'
            ELSE 'backlog'
        END AS status_group,
        CASE
            WHEN mapping.status_id IS NULL
             AND legacy.status_original IS NULL
             AND LOWER(TRIM(t.status_original)) NOT IN (
                 'aguardando início', 'aguardando inicio',
                 'em andamento', 'travado', 'concluído', 'concluido',
                 'inválido', 'invalido', 'enviado para evolução',
                 'enviado para evolucao', 'showcase'
             )
            THEN TRUE
            ELSE FALSE
        END AS unknown_status
    FROM descendant_edges AS d
    JOIN public.dim_ticket_jira AS t
      ON t.issue_key = d.child_issue_key
    LEFT JOIN public.dim_status AS legacy
      ON legacy.status_original = t.status_original
    LEFT JOIN LATERAL (
        SELECT m.*
        FROM public.dim_jira_status_mapping AS m
        WHERE m.is_active = TRUE
          AND (m.project_key = t.project_key OR m.project_key = '*')
          AND (
              m.status_id = t.status_original
              OR LOWER(TRIM(m.status_name)) = LOWER(TRIM(t.status_original))
          )
        ORDER BY
            CASE WHEN m.project_key = t.project_key THEN 0 ELSE 1 END,
            m.updated_at DESC
        LIMIT 1
    ) AS mapping ON TRUE
    ORDER BY
        d.epic_issue_key,
        d.child_issue_key,
        d.hierarchy_level
), annotated AS (
    SELECT
        r.*,
        NOT r.is_subtask AS is_effort_eligible,
        ARRAY_REMOVE(ARRAY[
            CASE
                WHEN NOT r.is_subtask
                 AND (r.original_estimate_seconds IS NULL
                      OR r.original_estimate_seconds <= 0)
                THEN 'NO_ESTIMATE'
            END,
            CASE WHEN r.unknown_status THEN 'UNKNOWN_STATUS' END,
            CASE
                WHEN r.planned_start_date IS NOT NULL
                 AND r.due_date IS NOT NULL
                 AND r.due_date < r.planned_start_date
                THEN 'INVALID_PLANNED_DATES'
            END,
            CASE
                WHEN r.resolved_at IS NOT NULL
                 AND r.resolved_at < r.created_at
                THEN 'INVALID_RESOLVED_DATE'
            END
        ]::TEXT[], NULL) AS inconsistency_codes
    FROM ticket_rows AS r
)
SELECT
    a.epic_issue_key,
    a.issue_key,
    a.relationship_type,
    a.hierarchy_level,
    a.issue_type_name,
    a.summary,
    a.project_key,
    a.project_name,
    a.squad_jira,
    a.status_original,
    a.status_group,
    a.status_mapping_name,
    a.status_mapping_group,
    a.created_at,
    a.resolved_at,
    a.planned_start_date,
    a.due_date,
    a.original_estimate_seconds,
    a.original_estimate_hours,
    a.parent_issue_key,
    a.source_present,
    a.last_seen_at,
    a.is_subtask,
    a.is_effort_eligible,
    a.inconsistency_codes,
    CARDINALITY(a.inconsistency_codes) > 0 AS has_inconsistency
FROM annotated AS a;

COMMENT ON VIEW public.vw_dashboard_project_child IS
    'Grão: uma linha por Epic × descendente direto ou subtarefa. Subtarefas ficam disponíveis para auditoria, mas is_effort_eligible=false e não entram no esforço.';

CREATE VIEW public.vw_dashboard_project_portfolio AS
WITH epic_scope AS (
    SELECT
        e.*,
        legacy.status_agrupado AS legacy_status_group,
        mapping.status_id AS mapped_status_id,
        mapping.status_name AS mapped_status_name,
        mapping.status_group AS mapped_status_group,
        mapping.starts_execution AS mapped_starts_execution,
        mapping.is_completion AS mapped_is_completion,
        CASE
            WHEN COALESCE(mapping.starts_execution, FALSE)
              OR COALESCE(mapping.status_group, '') = 'execucao'
              OR LOWER(TRIM(e.status_original)) IN (
                  'aguardando início', 'aguardando inicio',
                  'em andamento', 'travado'
              )
            THEN 'active'
            WHEN COALESCE(mapping.is_completion, FALSE)
              OR COALESCE(mapping.status_group, '') = 'concluido'
              OR LOWER(TRIM(e.status_original)) IN (
                  'concluído', 'concluido', 'inválido', 'invalido',
                  'enviado para evolução', 'enviado para evolucao',
                  'showcase'
              )
              OR legacy.status_agrupado = 'Concluído'
            THEN 'completed'
            ELSE 'backlog'
        END AS status_group,
        CASE
            WHEN mapping.status_id IS NULL
             AND legacy.status_original IS NULL
             AND LOWER(TRIM(e.status_original)) NOT IN (
                 'aguardando início', 'aguardando inicio',
                 'em andamento', 'travado', 'concluído', 'concluido',
                 'inválido', 'invalido', 'enviado para evolução',
                 'enviado para evolucao', 'showcase'
             )
            THEN TRUE
            ELSE FALSE
        END AS unknown_status
    FROM public.dim_ticket_jira AS e
    LEFT JOIN public.dim_status AS legacy
      ON legacy.status_original = e.status_original
    LEFT JOIN LATERAL (
        SELECT m.*
        FROM public.dim_jira_status_mapping AS m
        WHERE m.is_active = TRUE
          AND (m.project_key = e.project_key OR m.project_key = '*')
          AND (
              m.status_id = e.status_original
              OR LOWER(TRIM(m.status_name)) = LOWER(TRIM(e.status_original))
          )
        ORDER BY
            CASE WHEN m.project_key = e.project_key THEN 0 ELSE 1 END,
            m.updated_at DESC
        LIMIT 1
    ) AS mapping ON TRUE
    WHERE LOWER(TRIM(e.issue_type_name)) = 'epic'
      AND e.project_key IN ('ZGT', 'ZG', 'ZGTN', 'SRE')
      AND e.created_at >= TIMESTAMPTZ '2026-01-01 00:00:00+00'
      AND e.created_at < CURRENT_DATE + INTERVAL '1 day'
      AND e.source_present = TRUE
), transition_semantics AS (
    SELECT
        tr.issue_key,
        tr.transition_id,
        tr.transition_at,
        LOWER(TRIM(tr.to_status_name)) = 'em andamento'
            AS starts_execution,
        CASE
            WHEN COALESCE(mapping.starts_execution, FALSE)
              OR COALESCE(mapping.status_group, '') = 'execucao'
              OR LOWER(TRIM(tr.to_status_name)) IN (
                  'aguardando início', 'aguardando inicio',
                  'em andamento', 'travado'
              )
            THEN 'active'
            WHEN COALESCE(mapping.is_completion, FALSE)
              OR COALESCE(mapping.status_group, '') = 'concluido'
              OR LOWER(TRIM(tr.to_status_name)) IN (
                  'concluído', 'concluido', 'inválido', 'invalido',
                  'enviado para evolução', 'enviado para evolucao',
                  'showcase'
              )
            THEN 'completed'
            ELSE 'backlog'
        END AS status_group
    FROM public.fato_jira_status_transicao AS tr
    JOIN epic_scope AS e
      ON e.issue_key = tr.issue_key
    LEFT JOIN LATERAL (
        SELECT m.*
        FROM public.dim_jira_status_mapping AS m
        WHERE m.is_active = TRUE
          AND (m.project_key = e.project_key OR m.project_key = '*')
          AND (
              m.status_id = tr.to_status_id
              OR LOWER(TRIM(m.status_name)) = LOWER(TRIM(tr.to_status_name))
          )
        ORDER BY
            CASE WHEN m.project_key = e.project_key THEN 0 ELSE 1 END,
            m.updated_at DESC
        LIMIT 1
    ) AS mapping ON TRUE
    WHERE tr.source_present = TRUE
), ordered_transitions AS (
    SELECT
        s.*,
        ROW_NUMBER() OVER (
            PARTITION BY s.issue_key
            ORDER BY s.transition_at DESC, s.transition_id DESC
        ) AS latest_row
    FROM transition_semantics AS s
), transition_rollup AS (
    SELECT
        issue_key,
        MIN(transition_at) FILTER (WHERE starts_execution)
            AS actual_start_at,
        MAX(transition_at) FILTER (WHERE status_group = 'completed')
            AS last_completion_at,
        MAX(transition_at) FILTER (WHERE latest_row = 1)
            AS latest_transition_at,
        MAX(status_group) FILTER (WHERE latest_row = 1)
            AS latest_status_group
    FROM ordered_transitions
    GROUP BY issue_key
), child_rollup AS (
    SELECT
        c.epic_issue_key,
        COUNT(*) AS descendants_count,
        COUNT(*) FILTER (WHERE c.is_effort_eligible) AS child_ticket_count,
        COUNT(*) FILTER (WHERE c.is_subtask) AS subtask_count,
        COUNT(*) FILTER (
            WHERE c.is_effort_eligible
              AND c.original_estimate_seconds IS NOT NULL
              AND c.original_estimate_seconds > 0
        ) AS estimated_ticket_count,
        COUNT(*) FILTER (
            WHERE c.is_effort_eligible
              AND (c.original_estimate_seconds IS NULL
                   OR c.original_estimate_seconds <= 0)
        ) AS tickets_without_estimate_count,
        COALESCE(SUM(c.original_estimate_hours)
            FILTER (WHERE c.is_effort_eligible), 0.0) AS estimated_hours_total,
        COALESCE(SUM(c.original_estimate_hours)
            FILTER (
                WHERE c.is_effort_eligible
                  AND c.status_group = 'completed'
            ), 0.0) AS estimated_hours_completed,
        COALESCE(SUM(CASE WHEN c.has_inconsistency THEN 1 ELSE 0 END), 0)
            AS inconsistency_count,
        COALESCE(
            ARRAY_AGG(c.issue_key ORDER BY c.issue_key)
                FILTER (
                    WHERE c.is_effort_eligible
                      AND (c.original_estimate_seconds IS NULL
                           OR c.original_estimate_seconds <= 0)
                ),
            ARRAY[]::TEXT[]
        ) AS keys_without_estimate,
        COALESCE(
            ARRAY_AGG(c.issue_key ORDER BY c.issue_key)
                FILTER (WHERE c.has_inconsistency),
            ARRAY[]::TEXT[]
        ) AS keys_with_inconsistency
    FROM public.vw_dashboard_project_child AS c
    GROUP BY c.epic_issue_key
), portfolio_base AS (
    SELECT
        e.issue_key,
        e.summary,
        e.project_key,
        e.project_name,
        e.squad_jira,
        e.status_original,
        e.status_group,
        e.created_at,
        e.planned_start_date,
        e.due_date,
        e.resolved_at,
        e.source_present,
        e.last_seen_at,
        COALESCE(cr.descendants_count, 0) AS descendants_count,
        COALESCE(cr.child_ticket_count, 0) AS child_ticket_count,
        COALESCE(cr.subtask_count, 0) AS subtask_count,
        COALESCE(cr.estimated_ticket_count, 0) AS estimated_ticket_count,
        COALESCE(cr.tickets_without_estimate_count, 0)
            AS tickets_without_estimate_count,
        COALESCE(cr.estimated_hours_total, 0.0) AS estimated_hours_total,
        COALESCE(cr.estimated_hours_completed, 0.0)
            AS estimated_hours_completed,
        COALESCE(cr.inconsistency_count, 0) AS inconsistency_count,
        COALESCE(cr.keys_without_estimate, ARRAY[]::TEXT[])
            AS keys_without_estimate,
        COALESCE(cr.keys_with_inconsistency, ARRAY[]::TEXT[])
            AS keys_with_inconsistency,
        tr.actual_start_at,
        CASE
            WHEN tr.latest_transition_at IS NULL
             AND e.resolved_at IS NOT NULL
             AND e.resolved_at >= e.created_at
            THEN e.resolved_at
            WHEN tr.latest_status_group = 'completed'
            THEN COALESCE(e.resolved_at, tr.last_completion_at)
            ELSE NULL
        END AS actual_end_at,
        e.unknown_status
    FROM epic_scope AS e
    LEFT JOIN child_rollup AS cr
      ON cr.epic_issue_key = e.issue_key
    LEFT JOIN transition_rollup AS tr
      ON tr.issue_key = e.issue_key
), portfolio_annotated AS (
    SELECT
        p.*,
        CASE
            WHEN p.child_ticket_count = 0 THEN 'NO_CHILDREN'
            WHEN p.estimated_ticket_count = 0 THEN 'NO_ESTIMATES'
            WHEN p.estimated_ticket_count < p.child_ticket_count
                THEN 'PARTIAL_ESTIMATES'
            ELSE 'READY'
        END AS progress_status,
        ARRAY_REMOVE(ARRAY[
            CASE WHEN p.unknown_status THEN 'UNKNOWN_STATUS' END,
            CASE
                WHEN p.planned_start_date IS NOT NULL
                 AND p.due_date IS NOT NULL
                 AND p.due_date < p.planned_start_date
                THEN 'INVALID_PLANNED_DATES'
            END,
            CASE
                WHEN p.resolved_at IS NOT NULL
                 AND p.resolved_at < p.created_at
                THEN 'INVALID_RESOLVED_DATE'
            END,
            CASE
                WHEN p.actual_start_at IS NOT NULL
                 AND p.actual_end_at IS NOT NULL
                 AND p.actual_end_at < p.actual_start_at
                THEN 'INVALID_REAL_DATES'
            END
        ]::TEXT[], NULL) AS epic_inconsistency_codes
    FROM portfolio_base AS p
)
SELECT
    p.issue_key,
    p.summary,
    p.project_key,
    p.project_name,
    p.squad_jira,
    p.status_original,
    p.status_group,
    p.created_at,
    p.planned_start_date,
    p.due_date,
    p.actual_start_at,
    p.actual_end_at,
    GREATEST(
        0,
        CURRENT_DATE
            - (p.created_at AT TIME ZONE 'America/Sao_Paulo')::DATE
    ) AS days_created,
    CASE
        WHEN p.actual_start_at IS NULL THEN NULL
        ELSE GREATEST(
            0.0,
            EXTRACT(EPOCH FROM (
                COALESCE(p.actual_end_at, CURRENT_TIMESTAMP)
                - p.actual_start_at
            )) / 86400.0
        )
    END AS days_in_execution,
    p.resolved_at,
    p.descendants_count,
    p.child_ticket_count,
    p.subtask_count,
    p.estimated_ticket_count,
    p.tickets_without_estimate_count,
    p.estimated_hours_total,
    p.estimated_hours_completed,
    p.progress_status,
    p.progress_status AS progress_availability,
    CASE
        WHEN p.progress_status = 'READY'
        THEN ROUND(
            100.0 * p.estimated_hours_completed
                / NULLIF(p.estimated_hours_total, 0),
            2
        )
        ELSE NULL
    END AS progress_pct,
    p.keys_without_estimate,
    p.keys_with_inconsistency,
    p.inconsistency_count + CARDINALITY(p.epic_inconsistency_codes)
        AS inconsistency_count,
    ARRAY_REMOVE(
        p.keys_with_inconsistency || CASE
            WHEN CARDINALITY(p.epic_inconsistency_codes) > 0
            THEN ARRAY[p.issue_key]::TEXT[]
            ELSE ARRAY[]::TEXT[]
        END,
        NULL
    ) AS keys_with_project_inconsistency,
    p.epic_inconsistency_codes AS inconsistency_codes,
    p.source_present,
    p.last_seen_at
FROM portfolio_annotated AS p;

COMMENT ON VIEW public.vw_dashboard_project_portfolio IS
    'Grão: uma linha por Epic, independente de sprint. Progresso usa somente tickets filhos elegíveis e fica indisponível sem filhos, sem estimativas ou com estimativas parciais.';

CREATE VIEW public.vw_dashboard_project_freshness AS
WITH source AS (
    SELECT
        MAX(t.last_seen_at) AS last_success_at,
        MAX(t.updated_at) AS last_record_at,
        COUNT(*) AS record_count
    FROM public.dim_ticket_jira AS t
    WHERE LOWER(TRIM(t.issue_type_name)) = 'epic'
      AND t.project_key IN ('ZGT', 'ZG', 'ZGTN', 'SRE')
      AND t.created_at >= TIMESTAMPTZ '2026-01-01 00:00:00+00'
      AND t.created_at < CURRENT_DATE + INTERVAL '1 day'
      AND t.source_present = TRUE
)
SELECT
    'JIRA_PROJECTS'::TEXT AS source,
    source.last_success_at,
    source.last_record_at,
    NULL::TIMESTAMPTZ AS last_failure_at,
    CASE
        WHEN source.record_count = 0 OR source.last_success_at IS NULL
        THEN 'unavailable'
        ELSE 'available'
    END AS status,
    CASE
        WHEN source.last_success_at IS NULL THEN NULL
        ELSE EXTRACT(EPOCH FROM (
            CURRENT_TIMESTAMP - source.last_success_at
        )) / 60.0
    END AS delay_minutes,
    source.record_count
FROM source;

COMMENT ON VIEW public.vw_dashboard_project_freshness IS
    'Grão: uma linha de freshness do portfólio Jira; usa dim_ticket_jira e não depende de sprint ou etl_run_log.';

DO $phase29_grants$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'produtividade_reader'
    ) THEN
        GRANT SELECT ON
            public.vw_dashboard_project_child,
            public.vw_dashboard_project_portfolio,
            public.vw_dashboard_project_freshness
        TO produtividade_reader;
    END IF;
END
$phase29_grants$;
"""


def ensure_phase29_schema(engine: Engine) -> None:
    """Install the sprint-independent project portfolio views."""
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '30s'"))
        connection.execute(text("SET LOCAL statement_timeout = '5min'"))
        connection.execute(text(PROJECT_PORTFOLIO_VIEWS_SQL))
        connection.execute(
            text(
                "INSERT INTO public.etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE29_VERSION},
        )
