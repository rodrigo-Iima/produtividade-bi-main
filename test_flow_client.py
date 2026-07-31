"""Unit tests for the read-only first phase of the Flow integration."""

from dataclasses import asdict
from datetime import date, time

import pytest

from clients.flow_client import FlowAPIError, FlowClient
from clients.flow_dto import FLOW_TIMEZONE


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def _employee(
    person_id,
    contract_id,
    *,
    corporate_email=" Product.User@Example.com ",
):
    return {
        "idDaPessoa": person_id,
        "idDoContrato": contract_id,
        "nomeDaPessoa": "Pessoa de Teste",
        "nomeSocialDaPessoa": None,
        "emailCorporativo": corporate_email,
        "email": "personal@example.com",
        "situacao": 1,
        "dataDeAdmissao": "2024-01-15T00:00:00",
        "dataDeRescisao": None,
        "estabelecimento": "Unidade",
        "cargo": "Desenvolvedor",
        "funcao": "Engenharia",
        "postoDeTrabalho": "Remoto",
        "circuloHierarquico": "Produtos",
        "descricaoDoSetor": "Tecnologia",
        "descricaoDaUnidade": "Operação",
        # Sensitive fields returned by Flow must not cross the DTO boundary.
        "cpf": "00000000000",
        "pis": "00000000000",
        "salarioContratual": 999999,
        "numeroDaContaDeposito": "not-allowed",
    }


def _employee_page(records, total, status="Sucesso", errors=None):
    return {
        "retorno": {
            "status_processamento": 0,
            "status": status,
            "total": total,
            "registros": records,
            "erros": errors or [],
        }
    }


def test_fetches_active_employee_contracts_with_offset_pagination():
    session = FakeSession(
        [
            FakeResponse(
                _employee_page(
                    [_employee(10, 100), _employee(20, 200)],
                    total=3,
                )
            ),
            FakeResponse(
                _employee_page(
                    [_employee(30, 300, corporate_email=None)],
                    total=3,
                )
            ),
        ]
    )
    client = FlowClient(
        token="test-token",
        base_url="https://flow.example/Metadados.Api/",
        session=session,
    )

    contracts = client.get_active_employee_contracts(page_size=2)

    assert [contract.person_id for contract in contracts] == [
        "10",
        "20",
        "30",
    ]
    assert contracts[0].corporate_email == "product.user@example.com"
    assert contracts[2].corporate_email is None
    assert contracts[0].admitted_at.tzinfo == FLOW_TIMEZONE

    first_call = session.calls[0]
    second_call = session.calls[1]
    assert first_call[0].endswith("/api/v1/Funcionarios")
    assert first_call[1]["params"] == {
        "Situacao": 1,
        "Inicio": 0,
        "Quantidade": 2,
        "Ordem": "IdDaPessoa",
        "OrdemTipo": 0,
    }
    assert second_call[1]["params"]["Inicio"] == 2
    assert first_call[1]["headers"]["Authorization"] == "Bearer test-token"


def test_employee_dto_discards_sensitive_flow_fields():
    session = FakeSession(
        [FakeResponse(_employee_page([_employee(10, 100)], total=1))]
    )
    contract = FlowClient(
        token="test-token",
        session=session,
    ).get_active_employee_contracts()[0]

    allowed = asdict(contract)

    assert "cpf" not in allowed
    assert "pis" not in allowed
    assert "salarioContratual" not in allowed
    assert "numeroDaContaDeposito" not in allowed


def test_parses_point_moments_using_requested_person_and_sao_paulo_timezone():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "employee_id": None,
                    "hours_bank": {
                        "balance_in_minutes": 120,
                    },
                    "periods": [
                        {
                            "start_date": "2026-07-26",
                            "end_date": "2026-08-25",
                            "max_availability_date": "2026-08-30",
                            "events_summary": [],
                            "masters": [
                                {
                                    "master_date": "2026-07-28",
                                    "day_starts_at": "08:00",
                                    "kind": "Trabalhado",
                                    "confirmed": False,
                                    "pending_calculation": False,
                                    "default_moments": "8h diária",
                                    "moments": [
                                        "2026-07-28 08:05:00",
                                        "2026-07-28 12:00:00",
                                    ],
                                    "events": [],
                                    "errors": [
                                        "Faltam Marcações Obrigatórias"
                                    ],
                                    "warnings": [],
                                }
                            ],
                        }
                    ],
                }
            )
        ]
    )
    client = FlowClient(token="test-token", session=session)

    points = client.get_points(person_id=123)

    assert points.person_id == "123"
    assert len(points.periods) == 1
    day = points.periods[0].days[0]
    assert day.work_date == date(2026, 7, 28)
    assert day.day_starts_at == time(8, 0)
    assert day.moments[0].tzinfo == FLOW_TIMEZONE
    assert day.moments[0].utcoffset().total_seconds() == -3 * 60 * 60
    assert day.errors == ("Faltam Marcações Obrigatórias",)

    assert len(points.marks) == 2
    assert points.marks[0].order_in_day == 1
    assert points.marks[1].order_in_day == 2
    assert points.marks[0].period_start == date(2026, 7, 26)

    call = session.calls[0]
    assert call[0].endswith("/api/v1/Vibe/Ponto/Pontos")
    assert call[1]["params"] == {"idPessoa": "123"}


def test_accepts_person_without_materialized_point_data():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "employee_id": None,
                    "hours_bank": {},
                    "periods": [
                        {
                            "start_date": "2026-07-26",
                            "end_date": "2026-08-25",
                            "max_availability_date": "2026-08-30",
                            "events_summary": [],
                            "masters": [],
                        }
                    ],
                }
            )
        ]
    )

    points = FlowClient(
        token="test-token",
        session=session,
    ).get_points("no-data")

    assert points.person_id == "no-data"
    assert points.marks == ()


def test_rejects_functional_error_without_exposing_response_details():
    session = FakeSession(
        [
            FakeResponse(
                _employee_page(
                    [],
                    total=0,
                    status="Erro",
                    errors=[{"mensagem": "sensitive employee detail"}],
                )
            )
        ]
    )

    with pytest.raises(FlowAPIError) as error:
        FlowClient(
            token="test-token",
            session=session,
        ).get_active_employee_contracts()

    assert "falha funcional" in str(error.value)
    assert "sensitive employee detail" not in str(error.value)


def test_rejects_non_success_http_without_exposing_response_body():
    session = FakeSession(
        [
            FakeResponse(
                {"message": "sensitive upstream response"},
                status_code=401,
            )
        ]
    )

    with pytest.raises(FlowAPIError) as error:
        FlowClient(token="test-token", session=session).get_points("123")

    assert "HTTP 401" in str(error.value)
    assert "sensitive upstream response" not in str(error.value)
