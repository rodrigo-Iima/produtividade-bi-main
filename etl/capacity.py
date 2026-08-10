"""Build theoretical Sprint capacity from the current Clockify configuration."""

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from database.connection import SessionLocal
from models.bridge_clockify_user_group import BridgeClockifyUserGroup
from models.bridge_sprint_squad import BridgeSprintSquad
from models.dim_clockify_group import DimClockifyGroup
from models.dim_colaborador import DimColaborador
from models.dim_squad import DimSquad
from models.dim_sprint import DimSprint
from models.fato_sprint_capacidade import FatoSprintCapacidade


LOCAL_ZONE = ZoneInfo("America/Sao_Paulo")
WORKING_DAYS_PER_WEEK = Decimal("5")
CAPACITY_SOURCE = "clockify_current_configuration"
FLOW_NON_WORKING_KINDS = frozenset(
    {
        "compensado",
        "compensated",
        "férias",
        "ferias",
        "repouso remunerado",
        "ocorrência",
        "ocorrencia",
    }
)


def is_non_working_flow_kind(kind: str | None) -> bool:
    """Return whether a Flow day kind should reduce Sprint timebox capacity."""
    return (kind or "").strip().casefold() in FLOW_NON_WORKING_KINDS


def count_business_days(start_date: date, end_date: date) -> int:
    """Count weekdays in the half-open interval [start_date, end_date)."""
    total = 0
    current = start_date
    while current < end_date:
        if current.weekday() < 5:
            total += 1
        current = current.fromordinal(current.toordinal() + 1)
    return total


def _local_date(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_ZONE).date()


class SprintCapacityService:
    """Materialize one capacity row per eligible collaborator and Sprint."""

    def run(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict[str, int]:
        session = SessionLocal()
        try:
            sprint_query = session.query(DimSprint).filter(
                DimSprint.sprint_start.is_not(None),
                DimSprint.sprint_end.is_not(None),
                DimSprint.sprint_end > DimSprint.sprint_start,
            )
            if start_date is not None:
                start_at = datetime.combine(
                    start_date, time.min, tzinfo=LOCAL_ZONE
                )
                sprint_query = sprint_query.filter(DimSprint.sprint_start >= start_at)
            if end_date is not None:
                end_at = datetime.combine(
                    end_date, time.max, tzinfo=LOCAL_ZONE
                )
                sprint_query = sprint_query.filter(DimSprint.sprint_start <= end_at)

            sprints = sprint_query.order_by(
                DimSprint.sprint_start, DimSprint.sprint_id
            ).all()
            sprint_ids = [s.sprint_id for s in sprints]
            if not sprint_ids:
                session.commit()
                return {"sprints": 0, "rows": 0, "excluded_transversal": 0}

            session.execute(
                delete(FatoSprintCapacidade).where(
                    FatoSprintCapacidade.sprint_id.in_(sprint_ids)
                )
            )

            capacity_rows = self._capacity_rows(session, sprint_ids)
            now = datetime.now(timezone.utc)
            rows: list[FatoSprintCapacidade] = []
            seen: set[tuple[int, str]] = set()
            excluded_transversal = 0
            for row in capacity_rows:
                start_local = _local_date(row.sprint_start)
                end_local = _local_date(row.sprint_end)
                business_days = count_business_days(start_local, end_local)
                if business_days <= 0:
                    continue
                key = (row.sprint_id, row.user_id)
                if key in seen:
                    raise ValueError(
                        f"Capacidade duplicada para Sprint {row.sprint_id} "
                        f"e usuário {row.user_id}"
                    )
                seen.add(key)
                weekly_hours = Decimal(row.capacity_hours_week)
                rows.append(FatoSprintCapacidade(
                    sprint_id=row.sprint_id,
                    user_id=row.user_id,
                    squad_id=row.squad_id,
                    squad_name=row.squad_name,
                    papel=row.papel,
                    capacity_group_id=row.capacity_group_id,
                    capacity_group_name=row.capacity_group_name,
                    capacity_hours_week=weekly_hours,
                    sprint_start=row.sprint_start,
                    sprint_end=row.sprint_end,
                    business_days=business_days,
                    capacity_hours=(weekly_hours / WORKING_DAYS_PER_WEEK)
                    * Decimal(business_days),
                    source=CAPACITY_SOURCE,
                    calculated_at=now,
                ))

            session.add_all(rows)
            session.commit()
            print(
                f"[SprintCapacity] Loaded {len(rows)} collaborator × Sprint rows "
                f"for {len(sprints)} Sprints"
            )
            return {
                "sprints": len(sprints),
                "rows": len(rows),
                "excluded_transversal": excluded_transversal,
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _capacity_rows(session, sprint_ids: list[int]):
        """Return eligible collaborators mapped to their Squad's Sprints."""
        return session.execute(
            select(
                DimSprint.sprint_id,
                DimSprint.sprint_start,
                DimSprint.sprint_end,
                DimColaborador.user_id,
                DimColaborador.squad_id,
                DimColaborador.papel,
                DimSquad.nome.label("squad_name"),
                DimClockifyGroup.group_id.label("capacity_group_id"),
                DimClockifyGroup.name.label("capacity_group_name"),
                DimClockifyGroup.capacity_hours_week,
            )
            .select_from(DimSprint)
            .join(
                BridgeSprintSquad,
                BridgeSprintSquad.sprint_id == DimSprint.sprint_id,
            )
            .join(
                DimColaborador,
                DimColaborador.squad_id == BridgeSprintSquad.squad_id,
            )
            .join(DimSquad, DimSquad.squad_id == DimColaborador.squad_id)
            .join(
                BridgeClockifyUserGroup,
                BridgeClockifyUserGroup.user_id == DimColaborador.user_id,
            )
            .join(
                DimClockifyGroup,
                DimClockifyGroup.group_id == BridgeClockifyUserGroup.group_id,
            )
            .where(
                DimSprint.sprint_id.in_(sprint_ids),
                DimColaborador.is_active.is_(True),
                DimSquad.nome != "Transversal",
                BridgeClockifyUserGroup.is_current.is_(True),
                DimClockifyGroup.is_active.is_(True),
                DimClockifyGroup.group_type == "capacity",
            )
            .order_by(DimSprint.sprint_start, DimColaborador.user_id)
        ).mappings()


def run_sprint_capacity(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict[str, int]:
    return SprintCapacityService().run(start_date=start_date, end_date=end_date)
