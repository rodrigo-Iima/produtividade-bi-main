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


def _build_okr_status_and_date_filters(as_of_date: date) -> str:
    return (
        f"AND status = {OKR_COMPLETED_STATUS_JQL} "
        f'AND created >= "{OKR_YEAR}-01-01" '
        f'AND created <= "{as_of_date.isoformat()}" '
        "AND originalEstimate IS NOT EMPTY ORDER BY created DESC"
    )


def build_okr_bugs_jql(as_of_date: date | None = None) -> str:
    """Build the Jira scope for completed Bugs with a runtime upper bound."""
    end_date = as_of_date or execution_date()
    return (
        'project = ZG AND issuetype = "Bug" '
        f"{_build_okr_status_and_date_filters(end_date)}"
    )


def build_okr_adaptativa_jql(as_of_date: date | None = None) -> str:
    """Build the Jira scope for completed Operadoras Adaptativas."""
    end_date = as_of_date or execution_date()
    return (
        '((project = ZGT AND "squad[dropdown]" = "ZGT - Novas Operadoras") '
        'OR (project = ZG AND "squad[dropdown]" = Operadoras)) '
        'AND issuetype = "Adaptativa" '
        f"{_build_okr_status_and_date_filters(end_date)}"
    )


# An explicit environment override remains available for exceptional reruns.
OKR_BUGS_JQL = _env("OKR_BUGS_JQL") or build_okr_bugs_jql()
OKR_ADAPTATIVA_JQL = _env("OKR_ADAPTATIVA_JQL") or build_okr_adaptativa_jql()
