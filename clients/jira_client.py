import requests
from typing import Optional

from config.settings import (
    JIRA_URL,
    JIRA_EMAIL,
    JIRA_TOKEN
)


class JiraClient:
    """HTTP client for Jira REST API v3 (/search/jql endpoint)."""

    def __init__(self, timeout: int = 30):
        self.url = f"{JIRA_URL}/rest/api/3/search/jql"
        self.auth = (JIRA_EMAIL, JIRA_TOKEN)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        self.timeout = timeout

    def search(self, jql, fields=None, max_results=100):
        """Fetch issues with automatic pagination via nextPageToken.

        Returns a flat list of all issues matching the JQL query.
        """
        all_issues = []
        next_page_token = None

        while True:
            body = {
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
                timeout=self.timeout
            )

            if response.status_code != 200:
                print(f"[JiraClient] Error {response.status_code}: {response.text}")
                response.raise_for_status()

            data = response.json()
            issues = data.get("issues", [])
            all_issues.extend(issues)

            # Token-based pagination (new /search/jql endpoint)
            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

            print(f"[JiraClient] Fetched {len(all_issues)} issues so far...")

        print(f"[JiraClient] Total fetched: {len(all_issues)} issues")
        return all_issues

    def get_issue_changelog(self, issue_key: str) -> list[dict]:
        """Fetch changelog for a single issue.

        Returns a list of changelog entries with history items.
        """
        url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}/changelog"
        params = {"maxResults": 100}
        all_histories = []

        while True:
            response = requests.get(url, auth=self.auth, headers=self.headers, params=params, timeout=self.timeout)
            if response.status_code != 200:
                print(f"[JiraClient] Error fetching changelog for {issue_key}: {response.status_code} - {response.text}")
                response.raise_for_status()

            data = response.json()
            histories = data.get("values", [])
            all_histories.extend(histories)

            if data.get("isLast", True):
                break

            # Next page
            params["startAt"] = len(all_histories)

        return all_histories

    def get_sprint(self, sprint_id: int) -> Optional[dict]:
        """Fetch sprint metadata, including dates, from Jira Agile API."""
        url = f"{JIRA_URL}/rest/agile/1.0/sprint/{sprint_id}"
        response = requests.get(
            url,
            auth=self.auth,
            headers=self.headers,
            timeout=self.timeout,
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            print(
                f"[JiraClient] Error fetching sprint {sprint_id}: "
                f"{response.status_code} - {response.text}"
            )
            response.raise_for_status()
        return response.json()
