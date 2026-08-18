from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import time
from typing import Any, Callable, Optional

import requests

from config.settings import (
    JIRA_EMAIL,
    JIRA_HTTP_TIMEOUT_SECONDS,
    JIRA_MAX_RETRIES,
    JIRA_PAGE_SIZE,
    JIRA_RETRY_BACKOFF_SECONDS,
    JIRA_TOKEN,
    JIRA_URL,
)


class JiraClient:
    """Resilient Jira REST client with page and retry metrics.

    Jira Cloud's ``/search/jql`` endpoint uses a continuation token rather
    than ``startAt``. All callers keep receiving a flat list, while
    ``last_metrics`` exposes the number of pages, requests and retries made by
    the latest operation for ETL observability.
    """

    RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

    def __init__(
        self,
        timeout: int | float | None = None,
        max_retries: int | None = None,
        backoff_factor: float | None = None,
        session: Any | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ):
        self.url = f"{JIRA_URL}/rest/api/3/search/jql"
        self.auth = (JIRA_EMAIL, JIRA_TOKEN)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.timeout = (
            JIRA_HTTP_TIMEOUT_SECONDS if timeout is None else timeout
        )
        self.max_retries = (
            JIRA_MAX_RETRIES if max_retries is None else max_retries
        )
        self.backoff_factor = (
            JIRA_RETRY_BACKOFF_SECONDS
            if backoff_factor is None
            else backoff_factor
        )
        self.session = session
        self.sleep_fn = sleep_fn or time.sleep
        if self.timeout <= 0:
            raise ValueError("Jira timeout deve ser maior que zero")
        if self.max_retries < 0:
            raise ValueError("Jira max_retries não pode ser negativo")
        if self.backoff_factor < 0:
            raise ValueError("Jira backoff_factor não pode ser negativo")
        self.last_metrics: dict[str, int] = {}
        self._operation_metrics: dict[str, int] | None = None

    def search(
        self,
        jql: str,
        fields: list[str] | None = None,
        max_results: int | None = None,
    ) -> list[dict]:
        """Fetch all matching issues using token-based pagination."""
        all_issues: list[dict] = []
        next_page_token: str | None = None
        seen_page_tokens: set[str] = set()
        page_size = max_results or JIRA_PAGE_SIZE
        if page_size <= 0:
            raise ValueError("Jira page size deve ser maior que zero")
        metrics = self._start_operation()

        try:
            while True:
                body: dict[str, Any] = {
                    "jql": jql,
                    "maxResults": page_size,
                }
                if fields:
                    body["fields"] = fields
                if next_page_token:
                    body["nextPageToken"] = next_page_token

                response = self._request("POST", self.url, json=body)
                self._raise_for_unexpected_status(response, "search")

                data = response.json()
                issues = data.get("issues", [])
                if not isinstance(issues, list):
                    raise ValueError("Resposta Jira inválida: issues não é uma lista")
                all_issues.extend(issues)
                metrics["pages"] += 1
                metrics["records"] += len(issues)

                next_page_token = data.get("nextPageToken")
                if not next_page_token:
                    break
                if next_page_token in seen_page_tokens:
                    raise RuntimeError(
                        "Jira devolveu nextPageToken repetido; paginação interrompida"
                    )
                seen_page_tokens.add(next_page_token)
                print(
                    f"[JiraClient] Fetched {len(all_issues)} issues so far "
                    f"({metrics['pages']} pages)..."
                )

            print(
                f"[JiraClient] Total fetched: {len(all_issues)} issues "
                f"in {metrics['pages']} pages"
            )
            return all_issues
        finally:
            self._finish_operation(metrics)

    def get_issue_changelog(self, issue_key: str) -> list[dict]:
        """Fetch every changelog page for one issue."""
        url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}/changelog"
        params: dict[str, Any] = {"maxResults": 100}
        all_histories: list[dict] = []
        metrics = self._start_operation()

        try:
            while True:
                response = self._request("GET", url, params=params)
                self._raise_for_unexpected_status(
                    response,
                    f"changelog {issue_key}",
                )

                data = response.json()
                histories = data.get("values", [])
                if not isinstance(histories, list):
                    raise ValueError(
                        f"Resposta Jira inválida: changelog de {issue_key} não é uma lista"
                    )
                all_histories.extend(histories)
                metrics["pages"] += 1
                metrics["records"] += len(histories)

                if data.get("isLast", True) or not histories:
                    break
                params["startAt"] = len(all_histories)

            return all_histories
        finally:
            self._finish_operation(metrics)

    def get_sprint(self, sprint_id: int) -> Optional[dict]:
        """Fetch sprint metadata, including dates, from Jira Agile API."""
        url = f"{JIRA_URL}/rest/agile/1.0/sprint/{sprint_id}"
        response = self._request("GET", url)
        if response.status_code == 404:
            return None
        self._raise_for_unexpected_status(response, f"sprint {sprint_id}")
        return response.json()

    def get_board_quick_filters(self, board_id: int) -> list[dict]:
        """Fetch all quick filters configured on a Jira Agile board."""
        url = f"{JIRA_URL}/rest/agile/1.0/board/{board_id}/quickfilter"
        start_at = 0
        all_filters: list[dict] = []

        while True:
            response = self._request(
                "GET",
                url,
                params={"startAt": start_at, "maxResults": 50},
            )
            self._raise_for_unexpected_status(
                response,
                f"quick filters board {board_id}",
            )

            data = response.json()
            values = data.get("values", [])
            all_filters.extend(values)
            if data.get("isLast", True) or not values:
                break
            start_at += len(values)

        return all_filters

    def get_board_sprints(self, board_id: int) -> list[dict]:
        """Fetch the complete sprint catalog for an Agile board."""
        url = f"{JIRA_URL}/rest/agile/1.0/board/{board_id}/sprint"
        start_at = 0
        all_sprints: list[dict] = []

        while True:
            response = self._request(
                "GET",
                url,
                params={
                    "startAt": start_at,
                    "maxResults": 50,
                    "state": "active,closed,future",
                },
            )
            if (
                response.status_code == 400
                and "não aceita sprints" in response.text.casefold()
            ):
                print(
                    f"[JiraClient] Skipping board {board_id}: "
                    "board does not support sprints"
                )
                return all_sprints
            self._raise_for_unexpected_status(
                response,
                f"sprints board {board_id}",
            )

            data = response.json()
            values = data.get("values", [])
            all_sprints.extend(values)

            if data.get("isLast", True) or not values:
                break
            start_at += len(values)

        return all_sprints

    def get_boards(self, project_key_or_id: str | None = None) -> list[dict]:
        """Fetch Agile boards, optionally limited to a Jira project."""
        url = f"{JIRA_URL}/rest/agile/1.0/board"
        start_at = 0
        all_boards: list[dict] = []

        while True:
            params: dict[str, Any] = {"startAt": start_at, "maxResults": 50}
            if project_key_or_id:
                params["projectKeyOrId"] = project_key_or_id
            response = self._request("GET", url, params=params)
            self._raise_for_unexpected_status(response, "boards")

            data = response.json()
            values = data.get("values", [])
            all_boards.extend(values)
            if data.get("isLast", True) or not values:
                break
            start_at += len(values)

        return all_boards

    def _start_operation(self) -> dict[str, int]:
        metrics = {"requests": 0, "pages": 0, "records": 0, "retries": 0}
        self._operation_metrics = metrics
        return metrics

    def _finish_operation(self, metrics: dict[str, int]) -> None:
        self.last_metrics = dict(metrics)
        self._operation_metrics = None

    def _request(self, method: str, url: str, **kwargs):
        """Send one request, retrying transient failures with backoff."""
        kwargs.setdefault("auth", self.auth)
        kwargs.setdefault("headers", self.headers)
        kwargs.setdefault("timeout", self.timeout)

        for attempt in range(self.max_retries + 1):
            if self._operation_metrics is not None:
                self._operation_metrics["requests"] += 1
            try:
                if self.session is not None:
                    response = self.session.request(method, url, **kwargs)
                else:
                    response = requests.request(method, url, **kwargs)
            except requests.RequestException:
                if attempt >= self.max_retries:
                    raise
                self._sleep_before_retry(None, attempt)
                continue

            if response.status_code not in self.RETRYABLE_STATUS_CODES:
                return response
            if attempt >= self.max_retries:
                return response
            self._sleep_before_retry(response, attempt)

        raise RuntimeError("Jira request loop terminou inesperadamente")

    def _sleep_before_retry(self, response: Any | None, attempt: int) -> None:
        if self._operation_metrics is not None:
            self._operation_metrics["retries"] += 1
        delay = self._retry_after_seconds(response)
        if delay is None:
            delay = self.backoff_factor * (2**attempt)
        if delay > 0:
            self.sleep_fn(delay)

    @staticmethod
    def _retry_after_seconds(response: Any | None) -> float | None:
        if response is None:
            return None
        headers = getattr(response, "headers", {}) or {}
        value = headers.get("Retry-After") or headers.get("retry-after")
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(str(value))
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(
                    0.0,
                    (retry_at - datetime.now(timezone.utc)).total_seconds(),
                )
            except (TypeError, ValueError, OverflowError):
                return None

    @staticmethod
    def _raise_for_unexpected_status(response: Any, operation: str) -> None:
        if response.status_code == 200:
            return
        text = getattr(response, "text", "")
        print(
            f"[JiraClient] Error during {operation}: "
            f"{response.status_code} - {text}"
        )
        response.raise_for_status()
