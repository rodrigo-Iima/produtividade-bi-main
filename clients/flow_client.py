"""Read-only HTTP client for employee contracts and point data in Flow."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import requests

from clients.flow_dto import (
    FlowPayloadError,
    FlowPerson,
    FlowPoints,
)
from config.settings import (
    FLOW_API_TOKEN,
    FLOW_BASE_URL,
    FLOW_LOGIN_PASSWORD,
    FLOW_LOGIN_URL,
    FLOW_LOGIN_USERNAME,
    FLOW_TOKEN_REFRESH_SKEW_SECONDS,
)


class FlowAPIError(RuntimeError):
    """Raised when Flow cannot provide a valid successful response."""


class FlowClient:
    """Minimal read-only client for the first phase of the Flow integration."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        timeout: int = 30,
        session: requests.Session | None = None,
        username: str | None = None,
        password: str | None = None,
        login_url: str | None = None,
        refresh_skew_seconds: int | None = None,
    ):
        if timeout <= 0:
            raise ValueError("timeout deve ser maior que zero")
        if refresh_skew_seconds is not None and refresh_skew_seconds < 0:
            raise ValueError("refresh_skew_seconds deve ser maior ou igual a zero")

        self.api_url = (
            (base_url or FLOW_BASE_URL).rstrip("/") + "/api/v1"
        )
        self.timeout = timeout
        self._session = session or requests.Session()
        self._owns_session = session is None
        self._token = _normalize_token(
            FLOW_API_TOKEN if token is None else token
        )
        self._username = _normalize_text(
            FLOW_LOGIN_USERNAME if username is None else username
        )
        self._password = (
            FLOW_LOGIN_PASSWORD if password is None else password
        )
        self._login_url = (login_url or FLOW_LOGIN_URL).rstrip("/")
        self._refresh_skew_seconds = (
            FLOW_TOKEN_REFRESH_SKEW_SECONDS
            if refresh_skew_seconds is None
            else refresh_skew_seconds
        )
        self._headers = {
            "Accept": "application/json",
        }
        try:
            self._ensure_token()
        except Exception:
            if self._owns_session:
                self._session.close()
            raise

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def __enter__(self) -> FlowClient:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def get_active_people(
        self,
        page_size: int = 200,
    ) -> list[FlowPerson]:
        """Fetch active identities from the non-contractual People endpoint."""
        if page_size <= 0:
            raise ValueError("page_size deve ser maior que zero")

        start = 0
        people: list[FlowPerson] = []

        while True:
            payload = self._get(
                "/Pessoas",
                params={
                    "Inicio": start,
                    "Quantidade": page_size,
                },
            )
            records, total = _unwrap_records(payload, "/Pessoas")
            if not records:
                break

            try:
                people.extend(
                    person
                    for record in records
                    if (person := FlowPerson.from_api(record)).is_active
                )
            except FlowPayloadError as exc:
                raise FlowAPIError(
                    "Resposta inválida de /Pessoas"
                ) from exc
            start += len(records)
            if start >= total:
                break

        return people

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
        self._ensure_token()
        response = self._request_get(path, params)

        if response.status_code in {401, 403} and self._can_login():
            self._login()
            response = self._request_get(path, params)

        return self._parse_response(response, path)

    def _request_get(
        self,
        path: str,
        params: Mapping[str, Any],
    ) -> requests.Response:
        try:
            return self._session.get(
                f"{self.api_url}{path}",
                headers=self._authorized_headers(),
                params=dict(params),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise FlowAPIError(
                f"Falha de transporte ao consultar {path}"
            ) from exc

    def _ensure_token(self) -> None:
        if self._token and not _token_needs_refresh(
            self._token,
            self._refresh_skew_seconds,
        ):
            return
        if not self._can_login():
            raise ValueError(
                "Token Flow ausente ou expirado; configure "
                "FLOW_LOGIN_USERNAME e FLOW_LOGIN_PASSWORD"
            )
        self._login()

    def _can_login(self) -> bool:
        return bool(self._username and self._password)

    def _authorized_headers(self) -> dict[str, str]:
        if not self._token:
            raise FlowAPIError("Token Flow não disponível")
        return {
            **self._headers,
            "Authorization": f"Bearer {self._token}",
        }

    def _login(self) -> None:
        if not self._can_login():
            raise ValueError(
                "FLOW_LOGIN_USERNAME e FLOW_LOGIN_PASSWORD são obrigatórios "
                "para renovar o token Flow"
            )

        try:
            response = self._session.post(
                self._login_url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={
                    "Username": self._username,
                    "Senha": self._password,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise FlowAPIError(
                "Falha de transporte ao autenticar no Flow"
            ) from exc

        if response.status_code != 200:
            raise FlowAPIError(
                f"Flow Login retornou HTTP {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise FlowAPIError(
                "Flow Login retornou JSON inválido"
            ) from exc

        self._token = _extract_login_token(payload)

    def _parse_response(
        self,
        response: requests.Response,
        path: str,
    ) -> Mapping[str, Any]:
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


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _token_needs_refresh(token: str, skew_seconds: int) -> bool:
    expiration = _token_expiration(token)
    if expiration is None:
        return False
    return expiration <= datetime.now(timezone.utc) + timedelta(
        seconds=skew_seconds
    )


def _token_expiration(token: str) -> datetime | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * ((-len(payload)) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        expiration = claims.get("exp")
        if expiration is None:
            return None
        return datetime.fromtimestamp(float(expiration), tz=timezone.utc)
    except (IndexError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _extract_login_token(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        raise FlowAPIError("Flow Login retornou payload inesperado")

    envelope = payload.get("retorno", payload)
    if not isinstance(envelope, Mapping):
        raise FlowAPIError("Flow Login retornou envelope inesperado")

    status = envelope.get("status")
    errors = envelope.get("erros") or []
    if errors or (
        status is not None
        and str(status).strip().casefold() not in {"sucesso", "success"}
    ):
        raise FlowAPIError("Flow Login reportou falha funcional")

    records = envelope.get("registros") or []
    if not isinstance(records, list) or not records:
        raise FlowAPIError("Flow Login não retornou registros")
    first_record = records[0]
    if not isinstance(first_record, Mapping):
        raise FlowAPIError("Flow Login retornou registro inválido")

    token = _normalize_token(str(first_record.get("token") or ""))
    if not token:
        raise FlowAPIError("Flow Login não retornou token")
    return token


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
