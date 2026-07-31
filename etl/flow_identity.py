"""Synchronize Flow identities and map them to active Clockify users."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from sqlalchemy.orm import Session

from clients.flow_client import FlowClient
from clients.flow_dto import FlowEmployeeContract
from models.dim_colaborador import DimColaborador
from models.dim_flow_contrato import DimFlowContrato
from models.dim_flow_pessoa import DimFlowPessoa


class FlowIdentityError(ValueError):
    """Raised when contract rows disagree on one Flow person's identity."""


class FlowIdentityETL:
    """Fetch active Flow contracts and persist their identity mapping."""

    def __init__(
        self,
        client: FlowClient | None = None,
        session_factory: Callable[[], Session] | None = None,
    ):
        self._client = client
        self._session_factory = session_factory

    def run(
        self,
        observed_at: datetime | None = None,
    ) -> dict[str, int]:
        client = self._client or FlowClient()
        owns_client = self._client is None
        session_factory = self._session_factory
        if session_factory is None:
            from database.connection import SessionLocal

            session_factory = SessionLocal

        session = session_factory()
        try:
            contracts = client.get_active_employee_contracts()
            result = FlowIdentityService().sync(
                session,
                contracts,
                observed_at=observed_at,
            )
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            if owns_client:
                client.close()


@dataclass(frozen=True, slots=True)
class _FlowPersonInput:
    person_id: str
    name: str
    social_name: str | None
    corporate_email: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class _MappingDecision:
    clockify_user_id: str | None
    status: str
    method: str | None


class FlowIdentityService:
    """Persist active Flow people/contracts and resolve Clockify identities."""

    def set_manual_mapping(
        self,
        session: Session,
        flow_person_id: str,
        clockify_user_id: str,
        observed_at: datetime | None = None,
    ) -> None:
        """Set a validated manual override, taking precedence over email."""
        observed_at = observed_at or datetime.now(timezone.utc)
        person = session.get(DimFlowPessoa, flow_person_id)
        if person is None:
            raise FlowIdentityError(
                f"Pessoa Flow inexistente: {flow_person_id}"
            )

        collaborator = session.get(DimColaborador, clockify_user_id)
        if collaborator is None or not collaborator.is_active:
            raise FlowIdentityError(
                f"Colaborador Clockify ativo inexistente: {clockify_user_id}"
            )

        current_owner = (
            session.query(DimFlowPessoa)
            .filter(
                DimFlowPessoa.clockify_user_id == clockify_user_id,
                DimFlowPessoa.flow_person_id != flow_person_id,
            )
            .one_or_none()
        )
        if current_owner is not None:
            if current_owner.mapping_method == "manual":
                raise FlowIdentityError(
                    "Colaborador Clockify já possui outro mapeamento manual"
                )
            current_owner.clockify_user_id = None
            current_owner.mapping_status = "ambiguous_email"
            current_owner.mapping_method = None
            current_owner.updated_at = observed_at
            session.flush()

        person.clockify_user_id = clockify_user_id
        person.mapping_status = "mapped"
        person.mapping_method = "manual"
        person.updated_at = observed_at
        session.flush()

    def clear_manual_mapping(
        self,
        session: Session,
        flow_person_id: str,
        observed_at: datetime | None = None,
    ) -> None:
        """Remove a manual override so the next sync can remap by email."""
        person = session.get(DimFlowPessoa, flow_person_id)
        if person is None:
            raise FlowIdentityError(
                f"Pessoa Flow inexistente: {flow_person_id}"
            )
        if person.mapping_method != "manual":
            raise FlowIdentityError("Pessoa Flow não possui mapeamento manual")

        person.clockify_user_id = None
        person.mapping_status = "unmapped_no_match"
        person.mapping_method = None
        person.updated_at = observed_at or datetime.now(timezone.utc)
        session.flush()

    def sync(
        self,
        session: Session,
        contracts: Iterable[FlowEmployeeContract],
        observed_at: datetime | None = None,
    ) -> dict[str, int]:
        observed_at = observed_at or datetime.now(timezone.utc)
        contract_rows = list(contracts)
        people = _collect_people(contract_rows)

        existing_people = {
            row.flow_person_id: row
            for row in session.query(DimFlowPessoa).all()
        }
        existing_contracts = {
            row.flow_contract_id: row
            for row in session.query(DimFlowContrato).all()
        }

        for row in existing_people.values():
            row.is_active = False
            if row.mapping_method != "manual":
                row.clockify_user_id = None
                row.mapping_status = "unmapped_no_match"
                row.mapping_method = None
        for row in existing_contracts.values():
            row.is_active = False
        session.flush()

        decisions = self._mapping_decisions(
            session,
            people,
            existing_people,
        )

        for person in people.values():
            row = existing_people.get(person.person_id)
            if row is None:
                row = DimFlowPessoa(
                    flow_person_id=person.person_id,
                    name=person.name,
                    social_name=person.social_name,
                    corporate_email=person.corporate_email,
                    email=person.email,
                    mapping_status="unmapped_no_match",
                    is_active=True,
                    flow_last_seen_at=observed_at,
                    updated_at=observed_at,
                )
                session.add(row)
                existing_people[person.person_id] = row
            else:
                row.name = person.name
                row.social_name = person.social_name
                row.corporate_email = person.corporate_email
                row.email = person.email
                row.is_active = True
                row.flow_last_seen_at = observed_at
                row.updated_at = observed_at

            if row.mapping_method != "manual":
                decision = decisions[person.person_id]
                row.clockify_user_id = decision.clockify_user_id
                row.mapping_status = decision.status
                row.mapping_method = decision.method

        session.flush()

        for contract in contract_rows:
            row = existing_contracts.get(contract.contract_id)
            if row is None:
                row = DimFlowContrato(
                    flow_contract_id=contract.contract_id,
                    flow_person_id=contract.person_id,
                    status=contract.status,
                    flow_last_seen_at=observed_at,
                    updated_at=observed_at,
                )
                session.add(row)
                existing_contracts[contract.contract_id] = row

            row.flow_person_id = contract.person_id
            row.status = contract.status
            row.admitted_at = contract.admitted_at
            row.terminated_at = contract.terminated_at
            row.establishment = contract.establishment
            row.role = contract.role
            row.function = contract.function
            row.work_post = contract.work_post
            row.hierarchy_circle = contract.hierarchy_circle
            row.sector = contract.sector
            row.unit = contract.unit
            row.is_active = (
                contract.status == 1 and contract.terminated_at is None
            )
            row.flow_last_seen_at = observed_at
            row.updated_at = observed_at

        session.flush()

        active_people = [
            row
            for row in existing_people.values()
            if row.flow_person_id in people
        ]
        return {
            "people": len(people),
            "contracts": len(contract_rows),
            "mapped": sum(
                row.mapping_status == "mapped" for row in active_people
            ),
            "manual": sum(
                row.mapping_method == "manual" for row in active_people
            ),
            "unmapped_no_email": sum(
                row.mapping_status == "unmapped_no_email"
                for row in active_people
            ),
            "unmapped_no_match": sum(
                row.mapping_status == "unmapped_no_match"
                for row in active_people
            ),
            "ambiguous_email": sum(
                row.mapping_status == "ambiguous_email"
                for row in active_people
            ),
        }

    def _mapping_decisions(
        self,
        session: Session,
        people: dict[str, _FlowPersonInput],
        existing_people: dict[str, DimFlowPessoa],
    ) -> dict[str, _MappingDecision]:
        clockify_by_email: dict[str, set[str]] = defaultdict(set)
        for collaborator in session.query(DimColaborador).filter(
            DimColaborador.is_active.is_(True)
        ):
            email = _normalize_email(collaborator.email)
            if email:
                clockify_by_email[email].add(collaborator.user_id)

        manual_targets = {
            row.clockify_user_id: row.flow_person_id
            for row in existing_people.values()
            if row.mapping_method == "manual" and row.clockify_user_id
        }
        decisions: dict[str, _MappingDecision] = {}
        auto_candidates: dict[str, str] = {}

        for person in people.values():
            existing = existing_people.get(person.person_id)
            if existing is not None and existing.mapping_method == "manual":
                decisions[person.person_id] = _MappingDecision(
                    clockify_user_id=existing.clockify_user_id,
                    status="mapped",
                    method="manual",
                )
                continue

            decision = _match_by_email(person, clockify_by_email)
            decisions[person.person_id] = decision
            if decision.clockify_user_id:
                auto_candidates[person.person_id] = decision.clockify_user_id

        people_by_target: dict[str, list[str]] = defaultdict(list)
        for person_id, target in auto_candidates.items():
            people_by_target[target].append(person_id)

        for target, person_ids in people_by_target.items():
            manual_owner = manual_targets.get(target)
            collision = len(person_ids) > 1 or (
                manual_owner is not None and manual_owner not in person_ids
            )
            if collision:
                for person_id in person_ids:
                    decisions[person_id] = _MappingDecision(
                        clockify_user_id=None,
                        status="ambiguous_email",
                        method=None,
                    )

        return decisions


def _collect_people(
    contracts: list[FlowEmployeeContract],
) -> dict[str, _FlowPersonInput]:
    grouped: dict[str, list[FlowEmployeeContract]] = defaultdict(list)
    for contract in contracts:
        grouped[contract.person_id].append(contract)

    people: dict[str, _FlowPersonInput] = {}
    for person_id, rows in grouped.items():
        people[person_id] = _FlowPersonInput(
            person_id=person_id,
            name=_one_value(rows, "name", person_id, required=True),
            social_name=_one_value(rows, "social_name", person_id),
            corporate_email=_one_value(
                rows,
                "corporate_email",
                person_id,
            ),
            email=_one_value(rows, "email", person_id),
        )
    return people


def _one_value(
    rows: list[FlowEmployeeContract],
    field: str,
    person_id: str,
    required: bool = False,
):
    values = {
        getattr(row, field)
        for row in rows
        if getattr(row, field) is not None
    }
    if len(values) > 1:
        raise FlowIdentityError(
            f"Pessoa Flow {person_id} possui valores divergentes em {field}"
        )
    if values:
        return next(iter(values))
    if required:
        raise FlowIdentityError(
            f"Pessoa Flow {person_id} não possui {field}"
        )
    return None


def _match_by_email(
    person: _FlowPersonInput,
    clockify_by_email: dict[str, set[str]],
) -> _MappingDecision:
    has_email = False
    for method, email in (
        ("corporate_email", person.corporate_email),
        ("email", person.email),
    ):
        normalized = _normalize_email(email)
        if not normalized:
            continue
        has_email = True
        matches = clockify_by_email.get(normalized, set())
        if len(matches) > 1:
            return _MappingDecision(None, "ambiguous_email", None)
        if len(matches) == 1:
            return _MappingDecision(next(iter(matches)), "mapped", method)

    status = "unmapped_no_match" if has_email else "unmapped_no_email"
    return _MappingDecision(None, status, None)


def _normalize_email(value: str | None) -> str | None:
    normalized = str(value or "").strip().casefold()
    return normalized or None
