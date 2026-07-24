"""Small Jira REST client used by the OKR pipeline."""

from __future__ import annotations

import requests

from config.settings import JIRA_EMAIL, JIRA_TOKEN, JIRA_URL


class JiraClient:
    """HTTP client for Jira Cloud's token-paginated JQL search endpoint."""

    def __init__(self, timeout: int = 30):
        if not JIRA_URL:
            raise RuntimeError("JIRA_URL não está configurada")
        self.url = f"{JIRA_URL.rstrip('/')}/rest/api/3/search/jql"
        self.auth = (JIRA_EMAIL, JIRA_TOKEN)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.timeout = timeout

    def search(
        self,
        jql: str,
        *,
        fields: list[str] | None = None,
        max_results: int = 100,
    ) -> list[dict]:
        """Fetch all issues matching a JQL query."""
        all_issues: list[dict] = []
        next_page_token: str | None = None

        while True:
            body: dict[str, object] = {
                "jql": jql,
                "maxResults": max_results,
            }
            if fields:
                body["fields"] = fields
            if next_page_token:
                body["nextPageToken"] = next_page_token

            response = requests.post(
                self.url,
                auth=self.auth,
                headers=self.headers,
                json=body,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            all_issues.extend(data.get("issues", []))
            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

        return all_issues
