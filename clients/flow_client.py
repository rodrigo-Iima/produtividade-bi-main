"""Read-only HTTP client for employee contracts and point data in Flow."""

from __future__ import annotations

from typing import Any, Mapping

import requests

from clients.flow_dto import (
    FlowEmployeeContract,
    FlowPayloadError,
    FlowPoints,
)
from config.settings import FLOW_API_TOKEN, FLOW_BASE_URL


class FlowAPIError(RuntimeError):
    """Raised when Flow cannot provide a valid successful response."""


class FlowClient:
    """Minimal read-only client for the first phase of the Flow integration."""

    ACTIVE_STATUS = 1

    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        timeout: int = 30,
        session: requests.Session | None = None,
    ):
        normalized_token = _normalize_token(token or FLOW_API_TOKEN)
        if not normalized_token:
            raise ValueError(
                "FLOW_API_TOKEN não configurado; informe o token apenas "
                "por variável de ambiente"
            )
        if timeout <= 0:
            raise ValueError("timeout deve ser maior que zero")

        self.api_url = (
            (base_url or FLOW_BASE_URL).rstrip("/") + "/api/v1"
        )
        self.timeout = timeout
        self._session = session or requests.Session()
        self._owns_session = session is None
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {normalized_token}",
        }

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def __enter__(self) -> FlowClient:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def get_active_employee_contracts(
        self,
        page_size: int = 200,
    ) -> list[FlowEmployeeContract]:
        """Fetch every active Flow employee contract with offset pagination."""
        if page_size <= 0:
            raise ValueError("page_size deve ser maior que zero")

        start = 0
        contracts: list[FlowEmployeeContract] = []

        while True:
            payload = self._get(
                "/Funcionarios",
                params={
                    "Situacao": self.ACTIVE_STATUS,
                    "Inicio": start,
                    "Quantidade": page_size,
                    "Ordem": "IdDaPessoa",
                    "OrdemTipo": 0,
                },
            )
            records, total = _unwrap_records(payload, "/Funcionarios")
            if not records:
                break

            try:
                contracts.extend(
                    FlowEmployeeContract.from_api(record)
                    for record in records
                )
            except FlowPayloadError as exc:
                raise FlowAPIError(
                    "Resposta inválida de /Funcionarios"
                ) from exc
            start += len(records)
            if start >= total:
                break

        return contracts

    def get_points(self, person_id: str | int) -> FlowPoints:
        """Fetch the available point periods for one distinct Flow person."""
        normalized_person_id = str(person_id).strip()
        if not normalized_person_id:
            raise ValueError("person_id obrigatório")

        payload = self._get(
            "/Vibe/Ponto/Pontos",
            params={"idPessoa": normalized_person_id},
        )
        try:
            return FlowPoints.from_api(normalized_person_id, payload)
        except FlowPayloadError as exc:
            raise FlowAPIError(
                "Resposta inválida de /Vibe/Ponto/Pontos"
            ) from exc

    def _get(
        self,
        path: str,
        params: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        try:
            response = self._session.get(
                f"{self.api_url}{path}",
                headers=self._headers,
                params=dict(params),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise FlowAPIError(
                f"Falha de transporte ao consultar {path}"
            ) from exc

        if response.status_code != 200:
            raise FlowAPIError(
                f"Flow retornou HTTP {response.status_code} em {path}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise FlowAPIError(
                f"Flow retornou JSON inválido em {path}"
            ) from exc

        if not isinstance(payload, Mapping):
            raise FlowAPIError(
                f"Flow retornou payload inesperado em {path}"
            )
        return payload


def _normalize_token(token: str | None) -> str | None:
    if token is None:
        return None
    normalized = token.strip()
    if normalized.casefold().startswith("bearer "):
        normalized = normalized[7:].strip()
    return normalized or None


def _unwrap_records(
    payload: Mapping[str, Any],
    endpoint: str,
) -> tuple[list[Mapping[str, Any]], int]:
    retorno = payload.get("retorno")
    if not isinstance(retorno, Mapping):
        raise FlowAPIError(f"Resposta sem envelope retorno em {endpoint}")

    status = retorno.get("status")
    errors = retorno.get("erros") or []
    if errors or (
        status is not None
        and str(status).strip().casefold() not in {"sucesso", "success"}
    ):
        raise FlowAPIError(f"Flow reportou falha funcional em {endpoint}")

    records = retorno.get("registros") or []
    if not isinstance(records, list):
        raise FlowAPIError(f"registros inválido em {endpoint}")
    if not all(isinstance(record, Mapping) for record in records):
        raise FlowAPIError(f"registro inválido em {endpoint}")

    try:
        total = int(retorno.get("total", len(records)))
    except (TypeError, ValueError) as exc:
        raise FlowAPIError(f"total inválido em {endpoint}") from exc
    if total < 0:
        raise FlowAPIError(f"total inválido em {endpoint}")

    return records, total
