"""Persistence gateway for the hosted OKR snapshots.

The analysis remains in Python, while Blob operations are delegated to the
Node endpoint in ``api/blob.js``. That endpoint uses the official JavaScript
SDK so Vercel OIDC authentication is handled by the supported runtime.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import requests


SNAPSHOT_PREFIX = "okr/snapshots/"
GATEWAY_PATH = "/api/blob"
REQUEST_TIMEOUT_SECONDS = 120


class BlobGatewayError(RuntimeError):
    """Raised when the Node Blob gateway cannot complete an operation."""


def _gateway_url(request_headers: Any | None = None) -> str:
    """Build the internal gateway URL for the current Vercel deployment."""

    configured_url = os.getenv("BLOB_GATEWAY_URL")
    if configured_url:
        return configured_url.rstrip("/")

    host = None
    protocol = "https"
    if request_headers is not None:
        host = request_headers.get("Host") or request_headers.get("host")
        forwarded_protocol = (
            request_headers.get("X-Forwarded-Proto")
            or request_headers.get("x-forwarded-proto")
        )
        if forwarded_protocol:
            protocol = forwarded_protocol.split(",", 1)[0].strip()

    host = (
        host
        or os.getenv("VERCEL_URL")
        or os.getenv("VERCEL_PROJECT_PRODUCTION_URL")
    )
    if not host:
        raise BlobGatewayError(
            "Não foi possível determinar a URL do gateway Blob. "
            "Defina BLOB_GATEWAY_URL ou execute a função no Vercel."
        )

    if host.startswith("http://") or host.startswith("https://"):
        return f"{host.rstrip('/')}{GATEWAY_PATH}"
    return f"{protocol}://{host.rstrip('/')}{GATEWAY_PATH}"


def _authorization_headers() -> dict[str, str]:
    secret = os.getenv("CRON_SECRET")
    if not secret:
        raise BlobGatewayError("CRON_SECRET não configurado para o gateway Blob.")
    return {"Authorization": f"Bearer {secret}"}


def _raise_for_gateway_error(response: requests.Response) -> None:
    if 200 <= response.status_code < 300:
        return

    try:
        detail = response.json()
    except ValueError:
        detail = response.text[:500]
    raise BlobGatewayError(
        f"Gateway Blob retornou HTTP {response.status_code}: {detail}"
    )


class SnapshotStore:
    """Store dated dashboard snapshots through the internal Blob gateway."""

    def __init__(self, *, request_headers: Any | None = None) -> None:
        self.gateway_url = _gateway_url(request_headers)
        self.headers = _authorization_headers()

    def write(self, payload: dict[str, Any], *, as_of_date: date) -> str:
        pathname = f"{SNAPSHOT_PREFIX}{as_of_date.isoformat()}.json"
        response = requests.post(
            self.gateway_url,
            headers={**self.headers, "Content-Type": "application/json"},
            json={"pathname": pathname, "snapshot": payload},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        _raise_for_gateway_error(response)
        result = response.json()
        return str(result.get("snapshot", pathname))

    def read_latest(self) -> dict[str, Any] | None:
        response = requests.get(
            self.gateway_url,
            headers=self.headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 404:
            return None
        _raise_for_gateway_error(response)
        return response.json()
