"""Materialize Jira Sprint × Squad mappings from boards and quick filters."""

from __future__ import annotations

from datetime import datetime, timezone
import re
import unicodedata
from typing import Optional

from clients.jira_client import JiraClient
from database.connection import SessionLocal
from etl.sprint_scope import sprint_is_in_scope
from models.bridge_sprint_squad import BridgeSprintSquad
from models.dim_jira_board import DimJiraBoard
from models.dim_jira_quick_filter import DimJiraQuickFilter
from models.dim_squad import DimSquad
from models.dim_squad_alias import DimSquadAlias
from models.dim_sprint import DimSprint


SQUAD_JQL_PATTERN = re.compile(
    r'"?squad\[dropdown\]"?\s*=\s*'
    r'(?:("([^"]+)")|(\'([^\']+)\')|([^\s()]+))',
    re.IGNORECASE,
)

EXPECTED_ZGT_SQUADS = frozenset({
    "ZGT - Evolução",
    "ZGT - RDSL",
    "ZGT - Operadoras",
})

# Some historical single-Squad boards do not expose a Squad quick filter.
# Their board name is still the Jira source of truth. These hints are only a
# fallback after the board's own quick filters have been inspected.
BOARD_NAME_SQUAD_HINTS = (
    ("sustentacao", "ZGT - Sustentação"),
    ("operadoras", "Operadoras"),
    ("nucleo", "Núcleo"),
    ("rdsl", "RDSL"),
    ("monitoramento", "Monitoramento"),
    ("sre", "Monitoramento"),
    ("settings", "Transversal"),
    ("qa", "Transversal"),
    ("ux/ui", "Transversal"),
    # PrevOps is the historical name of the shared/transversal stream in the
    # current Clockify dimension.
    ("prevops", "Transversal"),
)

JIRA_SQUAD_ALIASES = {
    "zgt - rede d'or": "ZGT - RDSL",
    "zgt - novas operadoras": "ZGT - Operadoras",
    "projetos rede d'or": "RDSL",
    "monitoramento sre": "Monitoramento",
}


class JiraQuickFilterService:
    """Load every supported Jira Sprint × Squad source mapping."""

    def __init__(self, client: JiraClient | None = None):
        self.client = client or JiraClient()

    def run(self) -> dict[str, int]:
        session = SessionLocal()
        try:
            sprints = session.query(DimSprint).all()
            if not sprints:
                raise RuntimeError("Nenhuma Sprint foi encontrada.")

            # The current Jira sprint payload can omit originBoardId for older
            # rows. Resolve it before choosing the board-level source.
            self._fill_missing_origin_boards(sprints)

            board_meta, board_filters = self._load_board_catalog(sprints)
            self._refresh_sprint_catalog(session, board_filters)
            sprints = session.query(DimSprint).all()
            self._fill_missing_origin_boards(sprints)
            board_meta, board_filters = self._load_board_catalog(sprints)
            zgt_board_id, zgt_filters = self._discover_zgt_squad_board(
                board_meta,
                board_filters,
            )

            aliases, squad_names_by_id = self._load_squad_aliases(session)
            board_squad_filters = self._build_board_squad_filters(
                board_filters,
                aliases,
            )
            zgt_squad_filters = self._extract_filter_map(
                zgt_filters,
                aliases,
            )
            if {
                squad_names_by_id[squad_id]
                for squad_id in zgt_squad_filters
            } != EXPECTED_ZGT_SQUADS:
                raise RuntimeError(
                    "O board ZGT não possui exatamente as três Squads "
                    f"esperadas: {sorted(squad_names_by_id[sid] for sid in zgt_squad_filters)}"
                )

            fetched_at = datetime.now(timezone.utc)
            links: list[BridgeSprintSquad] = []
            unresolved: list[str] = []
            used_board_ids = {zgt_board_id}

            for sprint in sprints:
                mappings = self._mappings_for_sprint(
                    sprint=sprint,
                    board_meta=board_meta,
                    board_squad_filters=board_squad_filters,
                    zgt_board_id=zgt_board_id,
                    zgt_squad_filters=zgt_squad_filters,
                    aliases=aliases,
                )
                if not mappings:
                    unresolved.append(
                        f"sprint={sprint.sprint_id} {sprint.sprint_name!r} "
                        f"board={sprint.origin_board_id}"
                    )
                    continue

                used_board_ids.update(mapping[2] for mapping in mappings)
                links.extend(
                    BridgeSprintSquad(
                        sprint_id=sprint.sprint_id,
                        squad_id=squad_id,
                        board_id=board_id,
                        quick_filter_id=quick_filter_id,
                        mapping_source=mapping_source,
                        mapped_at=fetched_at,
                    )
                    for squad_id, quick_filter_id, board_id, mapping_source
                    in mappings
                )

            if unresolved:
                print(
                    "[JiraQuickFilters] Sprints sem uma fonte de Squad "
                    "explícita (mantidas fora da ponte):"
                )
                for item in unresolved:
                    print(f"  - {item}")

            # Persist the source catalog and replace the bridge atomically.
            session.query(BridgeSprintSquad).delete(synchronize_session=False)
            session.query(DimJiraQuickFilter).delete(synchronize_session=False)
            session.query(DimJiraBoard).delete(synchronize_session=False)

            source_boards = [
                board_meta[board_id]
                for board_id in sorted(used_board_ids)
                if board_id in board_meta
            ]
            session.add_all(
                DimJiraBoard(
                    board_id=self._parse_int(board.get("id")),
                    board_name=str(board.get("name") or "")[:200],
                )
                for board in source_boards
            )

            filter_rows: list[DimJiraQuickFilter] = []
            for board_id in sorted(used_board_ids):
                for raw_filter in board_filters.get(board_id, []):
                    quick_filter_id = self._parse_int(raw_filter.get("id"))
                    if quick_filter_id is None:
                        continue
                    filter_rows.append(DimJiraQuickFilter(
                        board_id=board_id,
                        quick_filter_id=quick_filter_id,
                        name=str(raw_filter.get("name") or "")[:200],
                        jql=str(raw_filter.get("jql") or "").strip(),
                        active=True,
                        fetched_at=fetched_at,
                    ))

            session.add_all(filter_rows)
            session.flush()
            session.add_all(links)
            session.commit()

            result = {
                "boards": len(used_board_ids),
                "quick_filters": len(filter_rows),
                "sprints": len(sprints),
                "unresolved_sprints": len(unresolved),
                "sprint_squad_links": len(links),
            }
            print(
                "[JiraQuickFilters] Loaded "
                f"{result['boards']} boards, "
                f"{result['quick_filters']} quick filters and "
                f"{result['sprint_squad_links']} Sprint × Squad links; "
                f"unresolved_sprints={result['unresolved_sprints']}"
            )
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _load_board_catalog(
        self,
        sprints: list[DimSprint],
    ) -> tuple[dict[int, dict], dict[int, list[dict]]]:
        """Load origin boards plus ZGT boards used for shared quick filters."""
        board_meta: dict[int, dict] = {}
        for raw_board in self.client.get_boards():
            board_id = self._parse_int(raw_board.get("id"))
            if board_id is not None:
                board_meta[board_id] = raw_board

        # A ZGT sprint can have originBoardId=300 while its Squad quick filters
        # live on board 986, so inspect all ZGT boards as well as origins.
        zgt_board_ids: set[int] = set()
        for raw_board in self.client.get_boards("ZGT"):
            board_id = self._parse_int(raw_board.get("id"))
            if board_id is not None:
                zgt_board_ids.add(board_id)
                board_meta[board_id] = raw_board

        board_ids = {
            sprint.origin_board_id
            for sprint in sprints
            if sprint.origin_board_id is not None
        }
        board_filters: dict[int, list[dict]] = {}
        for board_id in sorted(board_ids | zgt_board_ids):
            # Fetching every Jira board is unnecessary. Fetch origins and ZGT
            # candidates; metadata for other boards remains available for the
            # board-name fallback.
            board_filters[board_id] = self.client.get_board_quick_filters(board_id)
        return board_meta, board_filters

    def _refresh_sprint_catalog(
        self,
        session,
        board_filters: dict[int, list[dict]],
    ) -> None:
        """Upsert Sprints directly from board catalogs, not only ticket fields."""
        now = datetime.now(timezone.utc)
        refreshed = 0
        for board_id in sorted(board_filters):
            for raw_sprint in self.client.get_board_sprints(board_id):
                sprint_id = self._parse_int(raw_sprint.get("id"))
                sprint_start = self._parse_datetime(raw_sprint.get("startDate"))
                sprint_state = str(raw_sprint.get("state") or "").strip()
                if sprint_id is None or not sprint_is_in_scope(
                    sprint_start,
                    sprint_state,
                    now,
                ):
                    continue

                sprint_end = self._parse_datetime(raw_sprint.get("endDate"))
                origin_board_id = self._parse_int(
                    raw_sprint.get("originBoardId") or raw_sprint.get("boardId")
                ) or board_id
                sprint = session.get(DimSprint, sprint_id)
                if sprint is None:
                    sprint = DimSprint(sprint_id=sprint_id)
                    session.add(sprint)
                sprint.sprint_name = str(
                    raw_sprint.get("name") or f"Sprint {sprint_id}"
                )[:200]
                sprint.sprint_start = sprint_start
                sprint.sprint_end = sprint_end
                sprint.sprint_state = sprint_state
                sprint.origin_board_id = origin_board_id
                refreshed += 1

        session.flush()
        print(f"[JiraQuickFilters] Sprint catalog refreshed: {refreshed} rows")

    @staticmethod
    def _parse_datetime(value) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _discover_zgt_squad_board(
        self,
        board_meta: dict[int, dict],
        board_filters: dict[int, list[dict]],
    ) -> tuple[int, list[dict]]:
        """Find the single board carrying all three shared ZGT Squad filters."""
        candidates: list[tuple[int, list[dict]]] = []
        for board_id, filters in board_filters.items():
            names = {
                self._canonical_zgt_name(name)
                for raw_filter in filters
                for name in self.extract_squad_names(
                    str(raw_filter.get("jql") or "")
                )
            }
            if EXPECTED_ZGT_SQUADS.issubset(names):
                candidates.append((board_id, filters))

        if len(candidates) != 1:
            raise RuntimeError(
                "Era esperado exatamente um board com os três quick "
                f"filters de Squad ZGT; encontrados {len(candidates)}. "
                f"Boards candidatos: {sorted(board_meta)}"
            )
        return candidates[0]

    def _mappings_for_sprint(
        self,
        sprint: DimSprint,
        board_meta: dict[int, dict],
        board_squad_filters: dict[int, dict[int, int]],
        zgt_board_id: int,
        zgt_squad_filters: dict[int, int],
        aliases: dict[str, int],
    ) -> list[tuple[int, Optional[int], int, str]]:
        """Return (squad, quick_filter, board, source) mappings for a Sprint."""
        if sprint.sprint_name.upper().startswith("ZGT-"):
            return [
                (squad_id, quick_filter_id, zgt_board_id, "jira_quick_filter")
                for squad_id, quick_filter_id in zgt_squad_filters.items()
            ]

        origin_board_id = sprint.origin_board_id
        if origin_board_id is not None:
            filter_map = board_squad_filters.get(origin_board_id, {})
            if filter_map:
                return [
                    (squad_id, quick_filter_id, origin_board_id, "jira_quick_filter")
                    for squad_id, quick_filter_id in filter_map.items()
                ]

            board = board_meta.get(origin_board_id)
            fallback_squad_id = self._board_name_squad_id(board, aliases)
            if fallback_squad_id is not None:
                return [(
                    fallback_squad_id,
                    None,
                    origin_board_id,
                    "jira_origin_board",
                )]
        return []

    def _load_squad_aliases(self, session) -> tuple[dict[str, int], dict[int, str]]:
        squad_names_by_id = {
            squad_id: name
            for squad_id, name in session.query(
                DimSquad.squad_id,
                DimSquad.nome,
            )
        }
        aliases = {
            self._normalize(raw_name): squad_id
            for raw_name, squad_id in session.query(
                DimSquadAlias.nome_bruto,
                DimSquadAlias.squad_id,
            ).filter(DimSquadAlias.origem == "jira")
        }
        aliases.update({
            self._normalize(name): squad_id
            for squad_id, name in squad_names_by_id.items()
        })
        for raw_name, canonical_name in JIRA_SQUAD_ALIASES.items():
            squad_id = aliases.get(self._normalize(canonical_name))
            if squad_id is not None:
                aliases[self._normalize(raw_name)] = squad_id
        return aliases, squad_names_by_id

    def _build_board_squad_filters(
        self,
        board_filters: dict[int, list[dict]],
        aliases: dict[str, int],
    ) -> dict[int, dict[int, int]]:
        return {
            board_id: self._extract_filter_map(filters, aliases)
            for board_id, filters in board_filters.items()
        }

    def _extract_filter_map(
        self,
        raw_filters: list[dict],
        aliases: dict[str, int],
    ) -> dict[int, int]:
        result: dict[int, int] = {}
        for raw_filter in raw_filters:
            quick_filter_id = self._parse_int(raw_filter.get("id"))
            if quick_filter_id is None:
                continue
            for raw_name in self.extract_squad_names(
                str(raw_filter.get("jql") or "")
            ):
                squad_id = aliases.get(self._normalize(raw_name))
                if squad_id is not None:
                    result[squad_id] = quick_filter_id
        return result

    def _board_name_squad_id(
        self,
        board: dict | None,
        aliases: dict[str, int],
    ) -> int | None:
        if not board:
            return None
        board_name = self._normalize(str(board.get("name") or ""))
        matches = {
            aliases.get(self._normalize(canonical_name))
            for needle, canonical_name in BOARD_NAME_SQUAD_HINTS
            if self._normalize(needle) in board_name
        }
        matches.discard(None)
        return next(iter(matches)) if len(matches) == 1 else None

    def _fill_missing_origin_boards(self, sprints: list[DimSprint]) -> None:
        for sprint in sprints:
            if sprint.origin_board_id:
                continue
            metadata = self.client.get_sprint(sprint.sprint_id) or {}
            sprint.origin_board_id = self._parse_int(
                metadata.get("originBoardId") or metadata.get("boardId")
            )

    @classmethod
    def extract_squad_names(cls, jql: str) -> list[str]:
        """Extract one or more Squad values from a quick-filter JQL."""
        result: list[str] = []
        for match in SQUAD_JQL_PATTERN.finditer(jql or ""):
            value = next(group for group in match.groups() if group is not None)
            value = value.strip('"\'').strip()
            if value and value not in result:
                result.append(value)
        return result

    @staticmethod
    def _canonical_zgt_name(value: str) -> str:
        normalized = JiraQuickFilterService._normalize(value)
        aliases = {
            JiraQuickFilterService._normalize("ZGT - Rede D'or"): "ZGT - RDSL",
            JiraQuickFilterService._normalize("ZGT - Novas Operadoras"): "ZGT - Operadoras",
        }
        return aliases.get(normalized, value)

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        normalized = "".join(
            char for char in normalized
            if not unicodedata.combining(char)
        )
        return " ".join(normalized.strip().casefold().split())

    @staticmethod
    def _parse_int(value) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


def run_jira_quick_filters() -> dict[str, int]:
    return JiraQuickFilterService().run()
