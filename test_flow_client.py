"""Unit tests for the read-only first phase of the Flow integration."""

from dataclasses import asdict
from datetime import date, time
import base64
import json

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
    def __init__(self, responses, post_responses=None):
        self.responses = list(responses)
        self.post_responses = list(post_responses or [])
        self.calls = []
        self.post_calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_responses.pop(0)

    def close(self):
        self.closed = True


def _person(
    person_id,
    *,
    corporate_email=" Product.User@Example.com ",
    personal_email="personal@example.com",
    active=1,
):
    return {
        "id": person_id,
        "nome": "Pessoa de Teste",
        "nomeSocial": None,
        "ativo": active,
        "enderecosEletronicos": [
            {"tipoDeEnderecoEletronico": 1, "endereco": corporate_email},
            {"tipoDeEnderecoEletronico": 2, "endereco": personal_email},
        ],
        # Sensitive fields returned by Flow must not cross the DTO boundary.
        "cpf": "00000000000",
        "pis": "00000000000",
        "identidade": "not-allowed",
        "logradouro": "not-allowed",
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


def _login_response(token="fresh-token", status="Sucesso", errors=None):
    return FakeResponse(
        {
            "status_processamento": 1,
            "status": status,
            "total": 1,
            "registros": [{"token": token}],
            "erros": errors or [],
        }
    )


def _jwt_with_exp(expiration):
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": expiration}).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


def test_logs_in_automatically_when_static_token_is_absent():
    session = FakeSession(
        [FakeResponse(_employee_page([_person(10)], total=1))],
        post_responses=[_login_response()],
    )
    client = FlowClient(
        token="",
        username="flow-user",
        password="flow-password",
        login_url="https://flow.example/Metadados.Api/api/v1/Login",
        session=session,
    )

    client.get_active_people()

    login_call = session.post_calls[0]
    assert login_call[0].endswith("/api/v1/Login")
    assert login_call[1]["json"] == {
        "Username": "flow-user",
        "Senha": "flow-password",
    }
    assert session.calls[0][1]["headers"]["Authorization"] == (
        "Bearer fresh-token"
    )


def test_logs_in_before_request_when_jwt_is_expired():
    session = FakeSession(
        [FakeResponse(_employee_page([_person(10)], total=1))],
        post_responses=[_login_response("renewed-token")],
    )
    client = FlowClient(
        token=_jwt_with_exp(1),
        username="flow-user",
        password="flow-password",
        session=session,
    )

    client.get_active_people()

    assert len(session.post_calls) == 1
    assert session.calls[0][1]["headers"]["Authorization"] == (
        "Bearer renewed-token"
    )


def test_reauthenticates_once_after_unauthorized_response():
    session = FakeSession(
        [
            FakeResponse({}, status_code=401),
            FakeResponse(_employee_page([_person(10)], total=1)),
        ],
        post_responses=[_login_response("renewed-token")],
    )
    client = FlowClient(
        token="current-token",
        username="flow-user",
        password="flow-password",
        session=session,
    )

    client.get_active_people()

    assert len(session.calls) == 2
    assert len(session.post_calls) == 1
    assert session.calls[1][1]["headers"]["Authorization"] == (
        "Bearer renewed-token"
    )


def test_rejects_login_functional_error_without_exposing_response_details():
    session = FakeSession(
        [],
        post_responses=[
            _login_response(
                token="",
                status="Erro",
                errors=[{"mensagem": "sensitive login detail"}],
            )
        ],
    )

    with pytest.raises(FlowAPIError) as error:
        FlowClient(
            token="",
            username="flow-user",
            password="flow-password",
            session=session,
        )

    assert "falha funcional" in str(error.value)
    assert "sensitive login detail" not in str(error.value)


def test_fetches_active_people_with_offset_pagination():
    session = FakeSession(
        [
            FakeResponse(
                _employee_page(
                    [_person(10), _person(20)],
                    total=3,
                )
            ),
            FakeResponse(
                _employee_page(
                    [_person(30, corporate_email=None), _person(40, active=0)],
                    total=4,
                )
            ),
        ]
    )
    client = FlowClient(
        token="test-token",
        base_url="https://flow.example/Metadados.Api/",
        session=session,
    )

    people = client.get_active_people(page_size=2)

    assert [person.person_id for person in people] == [
        "10",
        "20",
        "30",
    ]
    assert people[0].corporate_email == "product.user@example.com"
    assert people[0].email == "personal@example.com"
    assert people[2].corporate_email is None

    first_call = session.calls[0]
    second_call = session.calls[1]
    assert first_call[0].endswith("/api/v1/Pessoas")
    assert first_call[1]["params"] == {
        "Inicio": 0,
        "Quantidade": 2,
    }
    assert second_call[1]["params"]["Inicio"] == 2
    assert first_call[1]["headers"]["Authorization"] == "Bearer test-token"


def test_person_dto_discards_sensitive_flow_fields():
    session = FakeSession(
        [FakeResponse(_employee_page([_person(10)], total=1))]
    )
    contract = FlowClient(
        token="test-token",
        session=session,
    ).get_active_people()[0]

    allowed = asdict(contract)

    assert "cpf" not in allowed
    assert "pis" not in allowed
    assert "identidade" not in allowed
    assert "logradouro" not in allowed


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
        ).get_active_people()

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
        FlowClient(
            token="test-token",
            username="",
            password="",
            session=session,
        ).get_points("123")

    assert "HTTP 401" in str(error.value)
    assert "sensitive upstream response" not in str(error.value)
