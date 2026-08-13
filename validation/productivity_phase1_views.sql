-- Checks read-only for the Phase 1 dashboard views.
-- Run with produtividade_reader; no individual rows are returned.

SELECT current_user,
       current_setting('transaction_read_only') AS transaction_read_only;

SELECT view_name,
       has_table_privilege(
           current_user,
           'public.' || quote_ident(view_name),
           'SELECT'
       ) AS can_select
  FROM (
      VALUES
          ('vw_dashboard_entry_tag_metrics'),
          ('vw_dashboard_ticket_actual_hours'),
          ('vw_dashboard_sprint_timebox_detail'),
          ('vw_dashboard_data_freshness')
  ) AS requested(view_name)
 ORDER BY view_name;

SELECT COUNT(*) AS rows,
       COUNT(DISTINCT entry_id) AS entries,
       ROUND(SUM(allocated_duration_hours), 4) AS allocated_hours,
       ROUND(SUM(duration_hours_original), 4) AS repeated_original_hours,
       COUNT(*) FILTER (WHERE allocated_duration_hours < 0) AS negative_allocations
  FROM public.vw_dashboard_entry_tag_metrics;

SELECT COUNT(*) AS rows,
       COUNT(DISTINCT (issue_key, sprint_id, user_id)) AS grain_rows,
       COUNT(*) - COUNT(DISTINCT (issue_key, sprint_id, user_id)) AS duplicate_rows,
       COUNT(*) FILTER (WHERE actual_hours < 0 OR dev_hours < 0)
           AS negative_hours
  FROM public.vw_dashboard_ticket_actual_hours;

SELECT COUNT(*) AS rows,
       COUNT(DISTINCT (sprint_id, user_id)) AS grain_rows,
       COUNT(*) - COUNT(DISTINCT (sprint_id, user_id)) AS duplicate_rows,
       COUNT(*) FILTER (WHERE capacity_hours < 0 OR hours_logged < 0)
           AS negative_measures
  FROM public.vw_dashboard_sprint_timebox_detail;

SELECT source,
       status,
       last_success_at,
       last_record_at,
       record_count
  FROM public.vw_dashboard_data_freshness
 ORDER BY source;
