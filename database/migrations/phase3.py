"""Create the reusable PostgreSQL views used by the Phase 3 metrics layer."""

from sqlalchemy import Engine, text


VIEW_VERSION = 3

VIEWS: dict[str, str] = {
    "vw_clockify_entry_detail": """
        SELECT
            e.entry_id, e.entry_date, e.started_at, e.ended_at,
            e.duration_seconds, e.duration_seconds / 3600.0 AS duration_hours,
            e.description, e.project_name, e.task_id, e.task_name,
            c.user_id, c.name AS collaborator_name, c.papel,
            c.squad_id, s.nome AS squad_name
        FROM fato_clockify_entry e
        JOIN dim_colaborador c ON c.user_id = e.user_id
        LEFT JOIN dim_squad s ON s.squad_id = c.squad_id
    """,
    "vw_clockify_entry_tag_detail": """
        SELECT
            e.entry_id, e.entry_date, e.duration_seconds,
            e.duration_seconds / 3600.0 AS duration_hours,
            e.user_id, c.name AS collaborator_name, c.papel,
            c.squad_id, squad.nome AS squad_name,
            t.tag_id, t.nome AS tag_name,
            t.nome_normalizado AS tag_name_normalized, et.foco_flag
        FROM fato_clockify_entry e
        JOIN dim_colaborador c ON c.user_id = e.user_id
        LEFT JOIN dim_squad squad ON squad.squad_id = c.squad_id
        JOIN bridge_clockify_entry_tag et ON et.entry_id = e.entry_id
        JOIN dim_tag t ON t.tag_id = et.tag_id
    """,
    "vw_clockify_entry_sprint_detail": """
        SELECT
            e.entry_id, e.entry_date, e.duration_seconds,
            e.duration_seconds / 3600.0 AS duration_hours,
            e.user_id, c.name AS collaborator_name, c.papel,
            c.squad_id, squad.nome AS squad_name,
            es.sprint_id, sp.sprint_name, sp.sprint_start,
            sp.sprint_end, sp.sprint_state,
            es.assignment_status, es.assignment_reason
        FROM fato_clockify_entry e
        JOIN dim_colaborador c ON c.user_id = e.user_id
        LEFT JOIN dim_squad squad ON squad.squad_id = c.squad_id
        JOIN bridge_clockify_entry_sprint es ON es.entry_id = e.entry_id
        LEFT JOIN dim_sprint sp ON sp.sprint_id = es.sprint_id
    """,
    "vw_clockify_entry_issue_detail": """
        SELECT
            e.entry_id, e.entry_date, e.duration_seconds,
            e.duration_seconds / 3600.0 AS duration_hours,
            e.user_id, c.name AS collaborator_name, c.papel,
            c.squad_id, squad.nome AS squad_name,
            ei.issue_key, ei.extraction_method,
            t.summary, t.project_key, t.project_name, t.squad_jira
        FROM fato_clockify_entry e
        JOIN dim_colaborador c ON c.user_id = e.user_id
        LEFT JOIN dim_squad squad ON squad.squad_id = c.squad_id
        JOIN bridge_clockify_entry_issue ei ON ei.entry_id = e.entry_id
        JOIN dim_ticket_jira t ON t.issue_key = ei.issue_key
    """,
    "vw_jira_ticket_sprint_detail": """
        SELECT
            r.issue_key, r.sprint_id, sp.sprint_name, sp.sprint_start,
            sp.sprint_end, sp.sprint_state, t.summary, t.status_original,
            COALESCE(st.status_agrupado, 'Não Classificado') AS status_agrupado,
            t.project_key, t.project_name, t.squad_jira,
            t.created_at, t.resolved_at, t.updated_at,
            r.sprint_entrada_at, r.planejado_no_inicio
        FROM fato_jira_ticket_sprint r
        JOIN dim_ticket_jira t ON t.issue_key = r.issue_key
        JOIN dim_sprint sp ON sp.sprint_id = r.sprint_id
        LEFT JOIN dim_status st ON st.status_original = t.status_original
    """,
}


def ensure_phase3_views(engine: Engine) -> None:
    """Replace Phase 3 views and record the view-layer version."""
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS etl_view_version (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))

        for view_name, definition in VIEWS.items():
            connection.execute(text(f'DROP VIEW IF EXISTS "{view_name}"'))
            connection.execute(text(f'CREATE VIEW "{view_name}" AS {definition}'))

        connection.execute(
            text(
                "INSERT INTO etl_view_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": VIEW_VERSION},
        )
