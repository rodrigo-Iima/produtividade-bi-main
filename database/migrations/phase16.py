"""Create the canonical Squad × Sprint source for Metabase linked filters."""

from sqlalchemy import Engine, text


PHASE16_VERSION = 16


FILTER_VIEW_SQL = """
DROP VIEW IF EXISTS public.vw_dashboard_filter_sprint_squad;

CREATE VIEW public.vw_dashboard_filter_sprint_squad AS
SELECT DISTINCT
    b.squad_id,
    sq.nome AS squad_name,
    b.sprint_id,
    s.sprint_name
FROM public.bridge_sprint_squad AS b
JOIN public.dim_squad AS sq
  ON sq.squad_id = b.squad_id
JOIN public.dim_sprint AS s
  ON s.sprint_id = b.sprint_id
WHERE NULLIF(BTRIM(sq.nome), '') IS NOT NULL
  AND NULLIF(BTRIM(s.sprint_name), '') IS NOT NULL;

COMMENT ON VIEW public.vw_dashboard_filter_sprint_squad IS
    'Fonte canônica de valores válidos para filtros vinculados Squad → Sprint no Metabase; derivada da ponte Sprint × Squad do Jira.';
"""


def ensure_phase16_schema(engine: Engine) -> None:
    """Create the idempotent filter-pair view from the Jira Sprint × Squad bridge."""
    with engine.begin() as connection:
        connection.execute(text(FILTER_VIEW_SQL))
        connection.execute(
            text(
                "INSERT INTO etl_schema_version(version) VALUES (:version) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": PHASE16_VERSION},
        )
