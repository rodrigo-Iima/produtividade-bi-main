import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

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
CLOCKIFY_PAGE_SIZE = int(_env("CLOCKIFY_PAGE_SIZE", "1000") or "1000")
CLOCKIFY_DEV_TAG = _env("CLOCKIFY_DEV_TAG", "Dev") or "Dev"
OKR_TICKET_TYPES = ("Bug", "Adaptativa")
OKR_COMPLETED_STATUS = "Concluído"
# Jira's JQL uses the normalized status alias even though the API returns the
# localized status name above.
OKR_COMPLETED_STATUS_JQL = "Done"


def execution_date() -> date:
    """Return today's date in the business timezone used by the OKR."""
    return datetime.now(ZoneInfo(OKR_TIMEZONE)).date()


def build_okr_bugs_jql(as_of_date: date | None = None) -> str:
    """Build the Jira scope with a runtime upper bound."""
    end_date = as_of_date or execution_date()
    issue_types = ", ".join(f'"{issue_type}"' for issue_type in OKR_TICKET_TYPES)
    return (
        f"project = ZG AND issuetype in ({issue_types}) "
        f"AND status = {OKR_COMPLETED_STATUS_JQL} "
        f'AND created >= "{OKR_YEAR}-01-01" '
        f'AND created <= "{end_date.isoformat()}" '
        "AND originalEstimate IS NOT EMPTY ORDER BY created DESC"
    )


# An explicit environment override remains available for exceptional reruns.
OKR_BUGS_JQL = _env("OKR_BUGS_JQL") or build_okr_bugs_jql()
