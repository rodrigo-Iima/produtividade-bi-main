import requests
from typing import List, Dict, Any, Optional

from config.settings import CLOCKIFY_API_KEY, CLOCKIFY_WORKSPACE_ID


class ClockifyClient:
    """HTTP client for Clockify API and Reports API."""

    def __init__(self, timeout: int = 30):
        self.api_url = "https://api.clockify.me/api/v1"
        self.reports_url = "https://reports.api.clockify.me/v1"
        self.headers = {
            "X-Api-Key": CLOCKIFY_API_KEY,
            "Content-Type": "application/json"
        }
        self.workspace_id = CLOCKIFY_WORKSPACE_ID
        self.timeout = timeout

    def get_users(self) -> List[Dict[str, Any]]:
        """Fetch all ACTIVE users in the workspace.
        GET /workspaces/{workspaceId}/users
        """
        url = f"{self.api_url}/workspaces/{self.workspace_id}/users"
        params = {
            "status": "ACTIVE",
            "page-size": 200
        }
        response = requests.get(url, headers=self.headers, params=params, timeout=self.timeout)
        if response.status_code != 200:
            print(f"[ClockifyClient] Error getting users: {response.text}")
            response.raise_for_status()
        return response.json()

    def get_user_groups(self) -> List[Dict[str, Any]]:
        """Fetch all user groups (used to resolve Role/Squad).
        GET /workspaces/{workspaceId}/user-groups
        """
        url = f"{self.api_url}/workspaces/{self.workspace_id}/user-groups"
        response = requests.get(url, headers=self.headers, timeout=self.timeout)
        if response.status_code != 200:
            print(f"[ClockifyClient] Error getting user groups: {response.text}")
            response.raise_for_status()
        return response.json()

    def get_projects(self) -> List[Dict[str, Any]]:
        """Fetch all projects in the workspace.
        GET /workspaces/{workspaceId}/projects
        """
        url = f"{self.api_url}/workspaces/{self.workspace_id}/projects"
        params = {"page-size": 500, "archived": "false"}
        all_projects = []
        while True:
            response = requests.get(url, headers=self.headers, params=params, timeout=self.timeout)
            if response.status_code != 200:
                print(f"[ClockifyClient] Error getting projects: {response.text}")
                response.raise_for_status()
            projects = response.json()
            all_projects.extend(projects)
            if len(projects) < 500:
                break
            params["page"] = params.get("page", 1) + 1
        return all_projects

    def get_project_tasks(self, project_id: str) -> List[Dict[str, Any]]:
        """Fetch all tasks for a specific project.
        GET /workspaces/{workspaceId}/projects/{projectId}/tasks
        """
        url = f"{self.api_url}/workspaces/{self.workspace_id}/projects/{project_id}/tasks"
        params = {"page-size": 500}
        all_tasks = []
        while True:
            response = requests.get(url, headers=self.headers, params=params, timeout=self.timeout)
            if response.status_code != 200:
                print(f"[ClockifyClient] Error getting tasks for project {project_id}: {response.text}")
                response.raise_for_status()
            tasks = response.json()
            all_tasks.extend(tasks)
            if len(tasks) < 500:
                break
            params["page"] = params.get("page", 1) + 1
        return all_tasks

    def get_detailed_report(self, start_date: str, end_date: str, page: int = 1, page_size: int = 1000) -> Dict[str, Any]:
        """Fetch detailed time entry reports.
        POST reports.api.clockify.me/v1/workspaces/{workspaceId}/reports/detailed
        
        Args:
            start_date: ISO 8601 string, e.g. "2026-01-01T00:00:00.000Z"
            end_date: ISO 8601 string, e.g. "2026-12-31T23:59:59.000Z"
            page: page number
            page_size: page size
        """
        url = f"{self.reports_url}/workspaces/{self.workspace_id}/reports/detailed"
        body = {
            "dateRangeStart": start_date,
            "dateRangeEnd": end_date,
            "detailedFilter": {
                "page": page,
                "pageSize": page_size
            }
        }
        response = requests.post(
            url,
            headers=self.headers,
            json=body,
            timeout=self.timeout,
        )
        if response.status_code != 200:
            print(f"[ClockifyClient] Error getting detailed report: {response.text}")
            response.raise_for_status()
        return response.json()
