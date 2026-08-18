"""Materialize the expensive productivity ticket/hour contract sources.

The public view names remain stable for Analytics Interno. The materialized
snapshots are refreshed after a successful ETL run, so dashboard requests do
not rebuild the complete Clockify/tag allocation graph on every cold query.
"""

from sqlalchemy import Engine, text


PHASE30_VERSION = 30


PRODUCTIVITY_SNAPSHOT_SQL = """
DROP VIEW IF EXISTS
    public.vw_dashboard_ticket_actual_hours,
    public.vw_dashboard_entry_tag_metrics
CASCADE;

DROP MATERIALIZED VIEW IF EXISTS
    public.mv_dashboard_ticket_actual_hours,
    public.mv_dashboard_entry_tag_metrics
CASCADE;

CREATE MATERIALIZED VIEW public.mv_dashboard_entry_tag_metrics AS
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

CREATE INDEX ix_mv_dashboard_entry_tag_metrics_entry_id
    ON public.mv_dashboard_entry_tag_metrics (entry_id);
CREATE INDEX ix_mv_dashboard_entry_tag_metrics_sprint_id
    ON public.mv_dashboard_entry_tag_metrics (sprint_id);

CREATE MATERIALIZED VIEW public.mv_dashboard_ticket_actual_hours AS
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
    FROM public.mv_dashboard_entry_tag_metrics
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

CREATE INDEX ix_mv_dashboard_ticket_actual_hours_sprint_id
    ON public.mv_dashboard_ticket_actual_hours (sprint_id);
CREATE INDEX ix_mv_dashboard_ticket_actual_hours_sprint_squad
    ON public.mv_dashboard_ticket_actual_hours (sprint_id, collaborator_squad_id);
CREATE INDEX ix_mv_dashboard_ticket_actual_hours_sprint_user
    ON public.mv_dashboard_ticket_actual_hours (sprint_id, user_id);
CREATE INDEX ix_mv_dashboard_ticket_actual_hours_sprint_type
    ON public.mv_dashboard_ticket_actual_hours (sprint_id, issue_type_name);

CREATE VIEW public.vw_dashboard_entry_tag_metrics AS
SELECT
    entry_id,
    entry_date,
    duration_hours_original,
    user_id,
    collaborator_name,
    papel,
    collaborator_squad_id,
    collaborator_squad_name,
    sprint_id,
    sprint_name,
    sprint_start,
    sprint_end,
    sprint_state,
    sprint_assignment_status,
    tag_id,
    tag_name,
    tag_name_normalized,
    foco_flag,
    foco_flag_dentro,
    valid_tag_count,
    allocated_duration_hours
FROM public.mv_dashboard_entry_tag_metrics;

COMMENT ON VIEW public.vw_dashboard_entry_tag_metrics IS
    'Contrato público sobre snapshot materializado; atualizar após cada ETL.';

CREATE VIEW public.vw_dashboard_ticket_actual_hours AS
SELECT
    issue_key,
    sprint_id,
    sprint_name,
    sprint_state,
    issue_type_name,
    jira_squad_id,
    jira_squad_name,
    status_original,
    status_agrupado,
    planejado_no_inicio,
    planejamento_status,
    user_id,
    collaborator_name,
    papel,
    collaborator_squad_id,
    collaborator_squad_name,
    linked_entry_count,
    first_entry_date,
    last_entry_date,
    actual_hours,
    dev_hours
FROM public.mv_dashboard_ticket_actual_hours;

COMMENT ON VIEW public.vw_dashboard_ticket_actual_hours IS
    'Contrato público sobre snapshot materializado; atualizar após cada ETL.';

CREATE OR REPLACE FUNCTION public.refresh_dashboard_snapshots()
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $refresh_dashboard_snapshots$
BEGIN
    REFRESH MATERIALIZED VIEW public.mv_dashboard_entry_tag_metrics;
    REFRESH MATERIALIZED VIEW public.mv_dashboard_ticket_actual_hours;
    ANALYZE public.mv_dashboard_entry_tag_metrics;
    ANALYZE public.mv_dashboard_ticket_actual_hours;
END
$refresh_dashboard_snapshots$;

REVOKE ALL ON FUNCTION public.refresh_dashboard_snapshots() FROM PUBLIC;

DO $phase30_grants$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'produtividade_reader'
    ) THEN
        GRANT SELECT ON
            public.mv_dashboard_entry_tag_metrics,
            public.mv_dashboard_ticket_actual_hours,
            public.vw_dashboard_entry_tag_metrics,
            public.vw_dashboard_ticket_actual_hours
        TO produtividade_reader;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'produtividade_etl'
    ) THEN
        GRANT EXECUTE ON FUNCTION public.refresh_dashboard_snapshots()
        TO produtividade_etl;
    END IF;
END
$phase30_grants$;
"""


def ensure_phase30_schema(engine: Engine) -> None:
    """Install the snapshots and stable public wrapper views."""
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '30s'"))
        connection.execute(text("SET LOCAL statement_timeout = '10min'"))
        connection.execute(text(PRODUCTIVITY_SNAPSHOT_SQL))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE30_VERSION},
        )


def refresh_phase30_snapshots(engine: Engine) -> None:
    """Refresh tag allocations before actual-ticket hours."""
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL statement_timeout = '10min'"))
        connection.execute(
            text("SELECT public.refresh_dashboard_snapshots()")
        )
