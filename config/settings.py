import os

from dotenv import load_dotenv


load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    return value.strip() if value else None


# API credentials are intentionally kept outside the repository.
JIRA_URL = _env("JIRA_URL")
JIRA_EMAIL = _env("JIRA_EMAIL")
JIRA_TOKEN = _env("JIRA_TOKEN")
CLOCKIFY_API_KEY = _env("CLOCKIFY_API_KEY")
CLOCKIFY_WORKSPACE_ID = _env("CLOCKIFY_WORKSPACE_ID")

# OKR scope and metric conventions.
OKR_YEAR = int(_env("OKR_YEAR", "2026") or "2026")
OKR_TIMEZONE = _env("OKR_TIMEZONE", "America/Sao_Paulo") or "America/Sao_Paulo"
JIRA_ESTIMATE_FIELD = _env("JIRA_ESTIMATE_FIELD", "timeoriginalestimate") or "timeoriginalestimate"
OKR_BUGS_JQL = _env(
    "OKR_BUGS_JQL",
    (
        f'issuetype = Bug AND created >= "{OKR_YEAR}-01-01" '
        f'AND created < "{OKR_YEAR + 1}-01-01" ORDER BY created ASC'
    ),
) or ""
CLOCKIFY_PAGE_SIZE = int(_env("CLOCKIFY_PAGE_SIZE", "1000") or "1000")
