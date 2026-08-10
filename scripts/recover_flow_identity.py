"""Recover Flow identity state from the last persisted contract snapshot.

This is intended for the narrow case where the Flow employee endpoint returns
an empty successful response after permissions are restricted. It never calls
Flow and uses only the identity/contract fields already stored locally.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select

from clients.flow_dto import FlowEmployeeContract
from database.connection import SessionLocal
from etl.flow_identity import FlowIdentityService
from models.dim_flow_contrato import DimFlowContrato
from models.dim_flow_pessoa import DimFlowPessoa


def _stored_active_contracts(session) -> list[FlowEmployeeContract]:
    people = {
        row.flow_person_id: row
        for row in session.scalars(select(DimFlowPessoa)).all()
    }
    contracts = session.scalars(
        select(DimFlowContrato)
        .where(
            DimFlowContrato.status == 1,
            DimFlowContrato.terminated_at.is_(None),
        )
        .order_by(DimFlowContrato.flow_contract_id)
    ).all()
    if not contracts:
        raise RuntimeError(
            "Nenhum contrato Flow ativo preservado para recuperação"
        )

    recovered = []
    for contract in contracts:
        person = people.get(contract.flow_person_id)
        if person is None:
            raise RuntimeError(
                "Contrato Flow sem pessoa correspondente; recuperação "
                "cancelada"
            )
        recovered.append(
            FlowEmployeeContract(
                person_id=person.flow_person_id,
                contract_id=contract.flow_contract_id,
                name=person.name,
                social_name=person.social_name,
                corporate_email=person.corporate_email,
                email=person.email,
                status=contract.status,
                admitted_at=contract.admitted_at,
                terminated_at=contract.terminated_at,
                establishment=contract.establishment,
                role=contract.role,
                function=contract.function,
                work_post=contract.work_post,
                hierarchy_circle=contract.hierarchy_circle,
                sector=contract.sector,
                unit=contract.unit,
            )
        )
    return recovered


def recover(*, apply: bool) -> dict[str, int | str]:
    session = SessionLocal()
    try:
        contracts = _stored_active_contracts(session)
        observed_at = max(
            row.flow_last_seen_at
            for row in session.scalars(select(DimFlowPessoa)).all()
        )
        result = FlowIdentityService().sync(
            session,
            contracts,
            observed_at=observed_at,
        )
        report = {
            "mode": "apply" if apply else "dry-run",
            "contracts_input": len(contracts),
            "people_input": result["people"],
            "mapped": result["mapped"],
            "unmapped_no_email": result["unmapped_no_email"],
            "unmapped_no_match": result["unmapped_no_match"],
            "ambiguous_email": result["ambiguous_email"],
            "people_active_after": int(
                session.scalar(
                    select(func.count())
                    .select_from(DimFlowPessoa)
                    .where(DimFlowPessoa.is_active.is_(True))
                )
                or 0
            ),
            "contracts_active_after": int(
                session.scalar(
                    select(func.count())
                    .select_from(DimFlowContrato)
                    .where(DimFlowContrato.is_active.is_(True))
                )
                or 0
            ),
        }
        if apply:
            session.commit()
        else:
            session.rollback()
        return report
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recupera identidades Flow do snapshot persistido"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="confirma a transação; sem isso executa apenas dry-run",
    )
    args = parser.parse_args()
    report = recover(apply=args.apply)
    for key, value in report.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
