"""Migration from the Phase 1 model to the normalized Phase 2 schema.

The migration is intentionally PostgreSQL-specific and transactional. It
renames the old tables, creates the new model, copies only fields that remain
part of the project, then drops the legacy tables. A version row makes the
operation idempotent on subsequent ETL runs.
"""

from __future__ import annotations

import re
import hashlib
import unicodedata
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Engine, text

from database.seed.data import SQUAD_MAPPINGS
from models.base import Base
from models.bridge_clockify_entry_issue import BridgeClockifyEntryIssue  # noqa: F401
from models.bridge_clockify_entry_sprint import BridgeClockifyEntrySprint  # noqa: F401
from models.bridge_clockify_entry_tag import BridgeClockifyEntryTag  # noqa: F401
from models.dim_calendario import DimCalendario  # noqa: F401
from models.dim_colaborador import DimColaborador  # noqa: F401
from models.dim_papel_tag import DimPapelTag  # noqa: F401
from models.dim_squad import DimSquad  # noqa: F401
from models.dim_squad_alias import DimSquadAlias  # noqa: F401
from models.dim_status import DimStatus  # noqa: F401
from models.dim_sprint import DimSprint  # noqa: F401
from models.dim_tag import DimTag  # noqa: F401
from models.dim_ticket_jira import DimTicketJira  # noqa: F401
from models.fato_clockify_entry import FatoClockifyEntry  # noqa: F401
from models.fato_jira_ticket_sprint import FatoJiraTicketSprint  # noqa: F401
from models.jira_sprint_changelog import JiraSprintChangelog  # noqa: F401


SCHEMA_VERSION = 2
VERSION_TABLE = "etl_schema_version"
LEGACY_PREFIX = "phase1_legacy_"
LEGACY_TABLES = (
    "bridge_clockify_jira",
    "dim_calendario",
    "dim_clockify_task",
    "dim_colaborador",
    "dim_sprint",
    "dim_squad",
    "dim_status_agrupado",
    "dim_tags_papel",
    "fato_clockify",
    "fato_jira",
    "jira_sprint_changelog",
)


def ensure_phase2_schema(engine: Engine) -> None:
    """Create or migrate the Phase 2 schema in one database transaction."""
    with engine.begin() as connection:
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS etl_schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        ))

        current_version = connection.execute(
            text("SELECT MAX(version) FROM etl_schema_version")
        ).scalar()

        if current_version is None:
            tables = _table_names(connection)
            if "fato_jira" in tables or "fato_clockify" in tables:
                _migrate_phase1_tables(connection)
            else:
                Base.metadata.create_all(connection)

            connection.execute(
                text(
                    "INSERT INTO etl_schema_version(version) VALUES (:version)"
                ),
                {"version": SCHEMA_VERSION},
            )
        elif current_version < SCHEMA_VERSION:
            raise RuntimeError(
                f"Schema version {current_version} is older than the supported "
                f"migration path. Apply migrations before running the ETL."
            )
        else:
            Base.metadata.create_all(connection)


def _table_names(connection) -> set[str]:
    rows = connection.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            """
        )
    )
    return {row[0] for row in rows}


def _migrate_phase1_tables(connection) -> None:
    legacy_names = _rename_legacy_tables(connection)

    Base.metadata.create_all(connection)

    legacy_jira = _fetch_rows(connection, legacy_names.get("fato_jira"))
    legacy_clockify = _fetch_rows(connection, legacy_names.get("fato_clockify"))
    legacy_bridge = _fetch_rows(
        connection, legacy_names.get("bridge_clockify_jira")
    )

    _copy_squads_and_collaborators(connection, legacy_names.get("dim_colaborador"))
    _copy_calendar(connection, legacy_names.get("dim_calendario"))
    _copy_statuses(connection, legacy_names.get("dim_status_agrupado"))
    _copy_tags(connection, legacy_names.get("dim_tags_papel"))
    _copy_sprints(connection, legacy_names.get("dim_sprint"), legacy_jira)
    _copy_tickets_and_sprints(connection, legacy_jira)
    _copy_clockify(connection, legacy_clockify)
    _copy_legacy_crossings(connection, legacy_bridge)
    _copy_changelog(connection, legacy_names.get("jira_sprint_changelog"))

    for legacy_name in legacy_names.values():
        connection.execute(text(f'DROP TABLE IF EXISTS "{legacy_name}"'))

    # These types belonged only to the old enum-backed changelog table.
    connection.execute(text("DROP TYPE IF EXISTS change_type_enum"))
    connection.execute(text("DROP TYPE IF EXISTS processing_status_enum"))


def _rename_legacy_tables(connection) -> dict[str, str]:
    tables = _table_names(connection)
    renamed: dict[str, str] = {}

    for table in LEGACY_TABLES:
        if table not in tables:
            continue
        legacy_name = f"{LEGACY_PREFIX}{table}"
        connection.execute(
            text(f'ALTER TABLE "{table}" RENAME TO "{legacy_name}"')
        )
        _rename_legacy_indexes(connection, legacy_name)
        renamed[table] = legacy_name

    return renamed


def _rename_legacy_indexes(connection, table_name: str) -> None:
    """Avoid PostgreSQL index-name collisions while legacy tables coexist."""
    index_names = connection.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = :table_name"
        ),
        {"table_name": table_name},
    ).scalars().all()

    for index_name in index_names:
        suffix = hashlib.sha1(index_name.encode("utf-8")).hexdigest()[:16]
        new_name = f"phase1_legacy_idx_{suffix}"
        connection.execute(
            text(
                f'ALTER INDEX {_quote_identifier(index_name)} '
                f'RENAME TO {_quote_identifier(new_name)}'
            )
        )


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _fetch_rows(connection, table_name: str | None) -> list[dict[str, Any]]:
    if not table_name:
        return []
    return [
        dict(row._mapping)
        for row in connection.execute(text(f'SELECT * FROM "{table_name}"'))
    ]


def _copy_squads_and_collaborators(connection, legacy_collaborator_table: str | None) -> None:
    legacy_collaborators = _fetch_rows(connection, legacy_collaborator_table)
    standard_names = {standard for _, standard in SQUAD_MAPPINGS}

    for row in legacy_collaborators:
        raw = _clean_text(row.get("squad"))
        if raw:
            standard_names.add(_standardize_squad(raw, "clockify"))

    for name in sorted(standard_names):
        connection.execute(
            text(
                "INSERT INTO dim_squad(nome) VALUES (:nome) "
                "ON CONFLICT (nome) DO NOTHING"
            ),
            {"nome": name},
        )

    squad_ids = {
        row.nome: row.squad_id
        for row in connection.execute(text("SELECT squad_id, nome FROM dim_squad"))
    }

    aliases: dict[tuple[str, str], int] = {}
    for raw, standard in SQUAD_MAPPINGS:
        squad_id = squad_ids[standard]
        aliases[("jira", raw)] = squad_id
        connection.execute(
            text(
                "INSERT INTO dim_squad_alias(origem, nome_bruto, squad_id) "
                "VALUES (:origem, :nome_bruto, :squad_id) "
                "ON CONFLICT (origem, nome_bruto) DO UPDATE SET squad_id = EXCLUDED.squad_id"
            ),
            {"origem": "jira", "nome_bruto": raw, "squad_id": squad_id},
        )

    for standard, squad_id in squad_ids.items():
        aliases[("clockify", standard)] = squad_id
        connection.execute(
            text(
                "INSERT INTO dim_squad_alias(origem, nome_bruto, squad_id) "
                "VALUES (:origem, :nome_bruto, :squad_id) "
                "ON CONFLICT (origem, nome_bruto) DO UPDATE SET squad_id = EXCLUDED.squad_id"
            ),
            {"origem": "clockify", "nome_bruto": standard, "squad_id": squad_id},
        )

    for row in legacy_collaborators:
        raw_squad = _clean_text(row.get("squad")) or "Transversal"
        standard = _standardize_squad(raw_squad, "clockify")
        squad_id = squad_ids.get(standard, squad_ids["Transversal"])
        aliases.setdefault(("clockify", raw_squad), squad_id)
        connection.execute(
            text(
                "INSERT INTO dim_squad_alias(origem, nome_bruto, squad_id) "
                "VALUES (:origem, :nome_bruto, :squad_id) "
                "ON CONFLICT (origem, nome_bruto) DO NOTHING"
            ),
            {"origem": "clockify", "nome_bruto": raw_squad, "squad_id": squad_id},
        )
        connection.execute(
            text(
                "INSERT INTO dim_colaborador(user_id, name, papel, squad_id) "
                "VALUES (:user_id, :name, :papel, :squad_id) "
                "ON CONFLICT (user_id) DO UPDATE SET name = EXCLUDED.name, "
                "papel = EXCLUDED.papel, squad_id = EXCLUDED.squad_id"
            ),
            {
                "user_id": row["user_id"],
                "name": row.get("name") or row["user_id"],
                "papel": row.get("papel"),
                "squad_id": squad_id,
            },
        )


def _copy_calendar(connection, legacy_table: str | None) -> None:
    for row in _fetch_rows(connection, legacy_table):
        connection.execute(
            text(
                "INSERT INTO dim_calendario(data, ano, mes_numero, mes_nome, "
                "dia_semana, dia_util, dia_do_mes) VALUES "
                "(:data, :ano, :mes_numero, :mes_nome, :dia_semana, :dia_util, :dia_do_mes)"
            ),
            row,
        )


def _copy_statuses(connection, legacy_table: str | None) -> None:
    for row in _fetch_rows(connection, legacy_table):
        connection.execute(
            text(
                "INSERT INTO dim_status(status_original, status_agrupado) "
                "VALUES (:status_original, :status_agrupado) "
                "ON CONFLICT (status_original) DO UPDATE SET status_agrupado = EXCLUDED.status_agrupado"
            ),
            row,
        )


def _copy_tags(connection, legacy_table: str | None) -> None:
    tag_ids: dict[str, int] = {}
    for row in _fetch_rows(connection, legacy_table):
        tag_name = _clean_text(row.get("tag_clockify"))
        role = _clean_text(row.get("papel"))
        if not tag_name or not role:
            continue

        normalized = _normalize(tag_name)
        if normalized not in tag_ids:
            connection.execute(
                text(
                    "INSERT INTO dim_tag(nome, nome_normalizado) VALUES (:nome, :normalizado) "
                    "ON CONFLICT (nome_normalizado) DO NOTHING"
                ),
                {"nome": tag_name, "normalizado": normalized},
            )
            tag_ids[normalized] = connection.execute(
                text("SELECT tag_id FROM dim_tag WHERE nome_normalizado = :normalizado"),
                {"normalizado": normalized},
            ).scalar_one()

        connection.execute(
            text(
                "INSERT INTO dim_papel_tag(papel, tag_id, foco) VALUES "
                "(:papel, :tag_id, :foco) ON CONFLICT (papel, tag_id) DO UPDATE SET foco = EXCLUDED.foco"
            ),
            {
                "papel": role,
                "tag_id": tag_ids[normalized],
                "foco": _clean_text(row.get("foco")) or "",
            },
        )


def _copy_sprints(connection, legacy_table: str | None, legacy_jira: list[dict[str, Any]]) -> None:
    sprints: dict[int, dict[str, Any]] = {}
    for row in _fetch_rows(connection, legacy_table):
        if row.get("sprint_id") is not None:
            sprints[int(row["sprint_id"])] = {
                "sprint_id": int(row["sprint_id"]),
                "sprint_name": row.get("sprint_name") or f"Sprint {row['sprint_id']}",
                "sprint_start": _as_utc(row.get("sprint_start")),
                "sprint_end": _as_utc(row.get("sprint_end")),
                "sprint_state": row.get("sprint_state"),
            }

    for row in legacy_jira:
        sprint_id = row.get("sprint_id")
        if sprint_id is None or int(sprint_id) in sprints:
            continue
        sprints[int(sprint_id)] = {
            "sprint_id": int(sprint_id),
            "sprint_name": row.get("sprint_name") or f"Sprint {sprint_id}",
            "sprint_start": _as_utc(row.get("sprint_start")),
            "sprint_end": _as_utc(row.get("sprint_end")),
            "sprint_state": None,
        }

    for row in sprints.values():
        connection.execute(
            text(
                "INSERT INTO dim_sprint(sprint_id, sprint_name, sprint_start, sprint_end, sprint_state) "
                "VALUES (:sprint_id, :sprint_name, :sprint_start, :sprint_end, :sprint_state) "
                "ON CONFLICT (sprint_id) DO UPDATE SET sprint_name = EXCLUDED.sprint_name, "
                "sprint_start = EXCLUDED.sprint_start, sprint_end = EXCLUDED.sprint_end, "
                "sprint_state = EXCLUDED.sprint_state"
            ),
            row,
        )


def _copy_tickets_and_sprints(connection, legacy_jira: list[dict[str, Any]]) -> None:
    latest_by_issue: dict[str, dict[str, Any]] = {}
    for row in sorted(
        legacy_jira,
        key=lambda item: (item.get("updated_at") or datetime.min, item.get("id") or 0),
        reverse=True,
    ):
        issue_key = row.get("issue_key")
        if not issue_key or issue_key in latest_by_issue:
            continue
        latest_by_issue[issue_key] = row

    for row in latest_by_issue.values():
        connection.execute(
            text(
                "INSERT INTO dim_ticket_jira(issue_key, summary, status_original, project_key, "
                "project_name, squad_jira, created_at, resolved_at, updated_at) VALUES "
                "(:issue_key, :summary, :status_original, :project_key, :project_name, "
                ":squad_jira, :created_at, :resolved_at, :updated_at)"
            ),
            {
                "issue_key": row["issue_key"],
                "summary": row.get("summary") or "",
                "status_original": row.get("status_original") or "",
                "project_key": row.get("project_key") or "",
                "project_name": row.get("project_name") or "",
                "squad_jira": row.get("squad_jira"),
                "created_at": _as_utc(row.get("created_at")),
                "resolved_at": _as_utc(row.get("resolved_at")),
                "updated_at": _as_utc(row.get("updated_at")),
            },
        )

    for row in legacy_jira:
        if not row.get("issue_key") or row.get("sprint_id") is None:
            continue
        connection.execute(
            text(
                "INSERT INTO fato_jira_ticket_sprint(issue_key, sprint_id, sprint_entrada_at, "
                "planejado_no_inicio) VALUES (:issue_key, :sprint_id, :entrada, :planejado) "
                "ON CONFLICT (issue_key, sprint_id) DO UPDATE SET sprint_entrada_at = EXCLUDED.sprint_entrada_at, "
                "planejado_no_inicio = EXCLUDED.planejado_no_inicio"
            ),
            {
                "issue_key": row["issue_key"],
                "sprint_id": row["sprint_id"],
                "entrada": _as_utc(row.get("sprint_entrada_at")),
                "planejado": (
                    True if row.get("planejado_no_inicio") == "Planejado"
                    else False if row.get("planejado_no_inicio") == "Adicionado Depois"
                    else None
                ),
            },
        )


def _copy_clockify(connection, legacy_rows: list[dict[str, Any]]) -> None:
    by_entry: dict[str, list[dict[str, Any]]] = {}
    for row in legacy_rows:
        if row.get("entry_id"):
            by_entry.setdefault(row["entry_id"], []).append(row)

    for entry_id, rows in by_entry.items():
        row = rows[0]
        user_id = row.get("user_id")
        if not user_id:
            continue
        if not connection.execute(
            text("SELECT 1 FROM dim_colaborador WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).scalar():
            transversal_id = connection.execute(
                text("SELECT squad_id FROM dim_squad WHERE nome = 'Transversal'")
            ).scalar()
            connection.execute(
                text(
                    "INSERT INTO dim_colaborador(user_id, name, papel, squad_id) "
                    "VALUES (:user_id, :name, NULL, :squad_id) "
                    "ON CONFLICT (user_id) DO NOTHING"
                ),
                {
                    "user_id": user_id,
                    "name": row.get("user_name") or user_id,
                    "squad_id": transversal_id,
                },
            )
        duration_hours = max(float(item.get("duration_hours") or 0) for item in rows)
        connection.execute(
            text(
                "INSERT INTO fato_clockify_entry(entry_id, user_id, description, project_name, "
                "task_id, task_name, started_at, ended_at, entry_date, duration_seconds) VALUES "
                "(:entry_id, :user_id, :description, :project_name, :task_id, :task_name, "
                "NULL, NULL, :entry_date, :duration_seconds)"
            ),
            {
                "entry_id": entry_id,
                "user_id": row["user_id"],
                "description": row.get("description"),
                "project_name": row.get("project") or "Sem Projeto",
                "task_id": row.get("task_id"),
                "task_name": row.get("task_name"),
                "entry_date": row["date"],
                "duration_seconds": round(duration_hours * 3600),
            },
        )

        for item in rows:
            tag_name = _clean_text(item.get("tag"))
            if not tag_name:
                continue
            tag_id = _ensure_tag(connection, tag_name)
            connection.execute(
                text(
                    "INSERT INTO bridge_clockify_entry_tag(entry_id, tag_id, foco_flag) "
                    "VALUES (:entry_id, :tag_id, :foco_flag) ON CONFLICT (entry_id, tag_id) DO NOTHING"
                ),
                {
                    "entry_id": entry_id,
                    "tag_id": tag_id,
                    "foco_flag": item.get("foco_flag") or "Fora do Foco",
                },
            )


def _copy_legacy_crossings(connection, legacy_rows: list[dict[str, Any]]) -> None:
    for row in legacy_rows:
        entry_id = row.get("entry_id")
        if not entry_id:
            continue
        issue_key = row.get("jira_issue_key")
        sprint_id = row.get("jira_sprint_id")

        if issue_key and connection.execute(
            text("SELECT 1 FROM fato_clockify_entry WHERE entry_id = :entry_id"),
            {"entry_id": entry_id},
        ).scalar():
            if connection.execute(
                text("SELECT 1 FROM dim_ticket_jira WHERE issue_key = :issue_key"),
                {"issue_key": issue_key},
            ).scalar():
                connection.execute(
                    text(
                        "INSERT INTO bridge_clockify_entry_issue(entry_id, issue_key, extraction_method) "
                        "VALUES (:entry_id, :issue_key, 'legacy_bridge') ON CONFLICT DO NOTHING"
                    ),
                    {"entry_id": entry_id, "issue_key": issue_key},
                )

            sprint_exists = sprint_id is not None and connection.execute(
                text("SELECT 1 FROM dim_sprint WHERE sprint_id = :sprint_id"),
                {"sprint_id": sprint_id},
            ).scalar()
            if sprint_exists or sprint_id is None:
                already_loaded = connection.execute(
                    text(
                        "SELECT 1 FROM bridge_clockify_entry_sprint "
                        "WHERE entry_id = :entry_id AND "
                        "((sprint_id = :sprint_id) OR (sprint_id IS NULL AND :sprint_id IS NULL))"
                    ),
                    {"entry_id": entry_id, "sprint_id": sprint_id},
                ).scalar()
                if not already_loaded:
                    connection.execute(
                        text(
                            "INSERT INTO bridge_clockify_entry_sprint(entry_id, sprint_id, assignment_status, assignment_reason) "
                            "VALUES (:entry_id, :sprint_id, :status, :reason)"
                        ),
                        {
                            "entry_id": entry_id,
                            "sprint_id": sprint_id,
                            "status": "atribuido" if sprint_id else "sem_sprint",
                            "reason": row.get("assignment_reason"),
                        },
                    )


def _copy_changelog(connection, legacy_table: str | None) -> None:
    for row in _fetch_rows(connection, legacy_table):
        issue_key = row.get("issue_key")
        if not issue_key:
            continue
        if not connection.execute(
            text("SELECT 1 FROM dim_ticket_jira WHERE issue_key = :issue_key"),
            {"issue_key": issue_key},
        ).scalar():
            continue

        sprint_id = row.get("sprint_id")
        if sprint_id is not None and not connection.execute(
            text("SELECT 1 FROM dim_sprint WHERE sprint_id = :sprint_id"),
            {"sprint_id": sprint_id},
        ).scalar():
            sprint_id = None

        fetched_at = _as_utc(row.get("fetched_at")) or datetime.now(timezone.utc)
        connection.execute(
            text(
                "INSERT INTO jira_sprint_changelog(issue_key, sprint_id, change_type, changed_at, "
                "fetched_at, processing_status, error_message) VALUES "
                "(:issue_key, :sprint_id, :change_type, :changed_at, :fetched_at, "
                ":processing_status, :error_message)"
            ),
            {
                "issue_key": issue_key,
                "sprint_id": sprint_id,
                "change_type": str(row.get("change_type") or "added"),
                "changed_at": _as_utc(row.get("changed_at")) or fetched_at,
                "fetched_at": fetched_at,
                "processing_status": str(row.get("processing_status") or "processed"),
                "error_message": row.get("error_message"),
            },
        )


def _ensure_tag(connection, tag_name: str) -> int:
    normalized = _normalize(tag_name)
    connection.execute(
        text(
            "INSERT INTO dim_tag(nome, nome_normalizado) VALUES (:nome, :normalizado) "
            "ON CONFLICT (nome_normalizado) DO NOTHING"
        ),
        {"nome": tag_name, "normalizado": normalized},
    )
    return connection.execute(
        text("SELECT tag_id FROM dim_tag WHERE nome_normalizado = :normalizado"),
        {"normalizado": normalized},
    ).scalar_one()


def _standardize_squad(raw: str, source: str) -> str:
    value = raw.strip()
    if source == "clockify":
        value = re.sub(r"^Squad\s*-?\s*", "", value, flags=re.IGNORECASE).strip()

    mapping = dict(SQUAD_MAPPINGS)
    if source == "jira":
        return mapping.get(value, value or "Sem Squad")
    if value in {standard for _, standard in SQUAD_MAPPINGS}:
        return value
    return mapping.get(value, value or "Transversal")


def _normalize(value: str) -> str:
    without_accents = "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", without_accents).strip().casefold()


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
