"""Tests for Flow ↔ Clockify identity mapping and dimension sync."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from clients.flow_dto import FlowEmployeeContract
from etl.clockify import ClockifyService
from etl.flow_identity import (
    FlowIdentityError,
    FlowIdentityETL,
    FlowIdentityService,
)
from models.base import Base
from models.dim_colaborador import DimColaborador
from models.dim_flow_contrato import DimFlowContrato
from models.dim_flow_pessoa import DimFlowPessoa
from models.dim_squad import DimSquad


OBSERVED_AT = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            DimSquad.__table__,
            DimColaborador.__table__,
            DimFlowPessoa.__table__,
            DimFlowContrato.__table__,
        ],
    )
    local_session = sessionmaker(bind=engine)()
    try:
        yield local_session
    finally:
        local_session.close()
        engine.dispose()


def _clockify_user(
    user_id,
    email,
    *,
    is_active=True,
):
    return DimColaborador(
        user_id=user_id,
        name=f"Clockify {user_id}",
        email=email,
        papel=None,
        squad_id=None,
        is_active=is_active,
    )


def _flow_contract(
    person_id,
    contract_id,
    *,
    corporate_email=None,
    email=None,
    name=None,
):
    return FlowEmployeeContract(
        person_id=str(person_id),
        contract_id=str(contract_id),
        name=name or f"Flow {person_id}",
        social_name=None,
        corporate_email=corporate_email,
        email=email,
        status=1,
        admitted_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        terminated_at=None,
        establishment="Matriz",
        role="Desenvolvedor",
        function="Engenharia",
        work_post="Remoto",
        hierarchy_circle="Produtos",
        sector="Tecnologia",
        unit="Operação",
    )


def test_sync_maps_people_by_email_and_keeps_all_active_contracts(session):
    session.add_all(
        [
            _clockify_user("u-dev", "dev@example.com"),
            _clockify_user("u-qa", "qa@example.com"),
            _clockify_user(
                "u-inactive",
                "dev@example.com",
                is_active=False,
            ),
        ]
    )
    session.flush()

    result = FlowIdentityService().sync(
        session,
        [
            _flow_contract(
                "p-dev",
                "c-dev-1",
                corporate_email="DEV@example.com",
            ),
            _flow_contract(
                "p-dev",
                "c-dev-2",
                corporate_email="DEV@example.com",
            ),
            _flow_contract(
                "p-qa",
                "c-qa",
                corporate_email="unknown@example.com",
                email="qa@example.com",
            ),
            _flow_contract("p-no-email", "c-none"),
            _flow_contract(
                "p-no-match",
                "c-unknown",
                corporate_email="missing@example.com",
            ),
        ],
        observed_at=OBSERVED_AT,
    )

    assert result == {
        "people": 4,
        "contracts": 5,
        "mapped": 2,
        "manual": 0,
        "unmapped_no_email": 1,
        "unmapped_no_match": 1,
        "ambiguous_email": 0,
    }

    dev = session.get(DimFlowPessoa, "p-dev")
    qa = session.get(DimFlowPessoa, "p-qa")
    assert dev.clockify_user_id == "u-dev"
    assert dev.mapping_method == "corporate_email"
    assert qa.clockify_user_id == "u-qa"
    assert qa.mapping_method == "email"
    assert session.query(DimFlowContrato).count() == 5
    assert (
        session.query(DimFlowContrato)
        .filter(DimFlowContrato.flow_person_id == "p-dev")
        .count()
        == 2
    )


def test_sync_preserves_manual_mapping_even_when_email_points_elsewhere(
    session,
):
    session.add_all(
        [
            _clockify_user("u-auto", "person@example.com"),
            _clockify_user("u-manual", "other@example.com"),
        ]
    )
    session.add(
        DimFlowPessoa(
            flow_person_id="p1",
            name="Existing",
            corporate_email="old@example.com",
            email=None,
            clockify_user_id="u-manual",
            mapping_status="mapped",
            mapping_method="manual",
            is_active=True,
            flow_last_seen_at=OBSERVED_AT,
            updated_at=OBSERVED_AT,
        )
    )
    session.flush()

    result = FlowIdentityService().sync(
        session,
        [
            _flow_contract(
                "p1",
                "c1",
                corporate_email="person@example.com",
            )
        ],
        observed_at=OBSERVED_AT,
    )

    person = session.get(DimFlowPessoa, "p1")
    assert person.clockify_user_id == "u-manual"
    assert person.mapping_method == "manual"
    assert person.mapping_status == "mapped"
    assert result["mapped"] == 1
    assert result["manual"] == 1


def test_manual_mapping_takes_precedence_and_can_be_cleared(session):
    session.add(_clockify_user("u1", "shared@example.com"))
    session.flush()
    service = FlowIdentityService()
    service.sync(
        session,
        [
            _flow_contract(
                "p-auto",
                "c-auto",
                corporate_email="shared@example.com",
            ),
            _flow_contract(
                "p-manual",
                "c-manual",
                corporate_email="missing@example.com",
            ),
        ],
        observed_at=OBSERVED_AT,
    )

    service.set_manual_mapping(
        session,
        "p-manual",
        "u1",
        observed_at=OBSERVED_AT,
    )

    automatic = session.get(DimFlowPessoa, "p-auto")
    manual = session.get(DimFlowPessoa, "p-manual")
    assert automatic.clockify_user_id is None
    assert automatic.mapping_status == "ambiguous_email"
    assert manual.clockify_user_id == "u1"
    assert manual.mapping_method == "manual"

    service.clear_manual_mapping(
        session,
        "p-manual",
        observed_at=OBSERVED_AT,
    )
    assert manual.clockify_user_id is None
    assert manual.mapping_status == "unmapped_no_match"
    assert manual.mapping_method is None


def test_sync_marks_email_collisions_as_ambiguous(session):
    session.add(_clockify_user("u1", "shared@example.com"))
    session.flush()

    result = FlowIdentityService().sync(
        session,
        [
            _flow_contract(
                "p1",
                "c1",
                corporate_email="shared@example.com",
            ),
            _flow_contract(
                "p2",
                "c2",
                corporate_email="shared@example.com",
            ),
        ],
        observed_at=OBSERVED_AT,
    )

    people = session.query(DimFlowPessoa).all()
    assert result["ambiguous_email"] == 2
    assert {person.mapping_status for person in people} == {
        "ambiguous_email"
    }
    assert all(person.clockify_user_id is None for person in people)


def test_sync_marks_flow_rows_missing_from_latest_snapshot_as_inactive(
    session,
):
    session.add(
        DimFlowPessoa(
            flow_person_id="old-person",
            name="Old",
            mapping_status="unmapped_no_match",
            is_active=True,
            flow_last_seen_at=OBSERVED_AT,
            updated_at=OBSERVED_AT,
        )
    )
    session.add(
        DimFlowContrato(
            flow_contract_id="old-contract",
            flow_person_id="old-person",
            status=1,
            is_active=True,
            flow_last_seen_at=OBSERVED_AT,
            updated_at=OBSERVED_AT,
        )
    )
    session.flush()

    FlowIdentityService().sync(
        session,
        [],
        observed_at=OBSERVED_AT,
    )

    assert session.get(DimFlowPessoa, "old-person").is_active is False
    assert session.get(DimFlowContrato, "old-contract").is_active is False


def test_sync_rejects_divergent_identity_values_across_contracts(session):
    with pytest.raises(FlowIdentityError, match="valores divergentes"):
        FlowIdentityService().sync(
            session,
            [
                _flow_contract(
                    "p1",
                    "c1",
                    corporate_email="one@example.com",
                ),
                _flow_contract(
                    "p1",
                    "c2",
                    corporate_email="two@example.com",
                ),
            ],
            observed_at=OBSERVED_AT,
        )


def test_clockify_email_normalization_matches_flow_mapping_rule():
    assert (
        ClockifyService._normalize_email(" Person@Example.COM ")
        == "person@example.com"
    )
    assert ClockifyService._normalize_email(None) is None


def test_identity_etl_fetches_syncs_and_commits():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            DimSquad.__table__,
            DimColaborador.__table__,
            DimFlowPessoa.__table__,
            DimFlowContrato.__table__,
        ],
    )
    factory = sessionmaker(bind=engine)
    with factory() as setup_session:
        setup_session.add(_clockify_user("u1", "person@example.com"))
        setup_session.commit()

    client = _FakeEmployeeClient(
        [
            _flow_contract(
                "p1",
                "c1",
                corporate_email="person@example.com",
            )
        ]
    )
    result = FlowIdentityETL(
        client=client,
        session_factory=factory,
    ).run(OBSERVED_AT)

    assert client.calls == 1
    assert result["people"] == 1
    assert result["contracts"] == 1
    assert result["mapped"] == 1
    with factory() as check_session:
        assert check_session.query(DimFlowPessoa).count() == 1
        assert check_session.query(DimFlowContrato).count() == 1
    engine.dispose()


class _FakeEmployeeClient:
    def __init__(self, contracts):
        self.contracts = contracts
        self.calls = 0

    def get_active_employee_contracts(self):
        self.calls += 1
        return self.contracts
