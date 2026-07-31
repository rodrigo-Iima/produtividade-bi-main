from dotenv import load_dotenv
import os

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(
        f"{name} inválido: use true/false, 1/0, yes/no ou on/off"
    )


def _env_nonnegative_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} inválido: use um número inteiro") from exc
    if parsed < 0:
        raise RuntimeError(f"{name} inválido: use zero ou um valor positivo")
    return parsed


def _env_day_of_month(name: str, default: int) -> int:
    parsed = _env_nonnegative_int(name, default)
    if not 1 <= parsed <= 31:
        raise RuntimeError(f"{name} inválido: use um dia entre 1 e 31")
    return parsed


def _env_csv_set(name: str, default: str = "") -> frozenset[str]:
    raw_value = os.getenv(name, default)
    return frozenset(
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    )


DB_HOST = os.getenv("POSTGRES_HOST")
DB_PORT = os.getenv("POSTGRES_PORT")
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DATABASE_URL = os.getenv("DATABASE_URL") or None
POSTGRES_SSLMODE = os.getenv("POSTGRES_SSLMODE") or None

JIRA_URL = os.getenv("JIRA_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")

# Clockify
CLOCKIFY_API_KEY = os.getenv("CLOCKIFY_API_KEY")
CLOCKIFY_WORKSPACE_ID = os.getenv("CLOCKIFY_WORKSPACE_ID")
CLOCKIFY_INCREMENTAL_LOOKBACK_DAYS = _env_nonnegative_int(
    "CLOCKIFY_INCREMENTAL_LOOKBACK_DAYS",
    10,
)

# Flow
FLOW_BASE_URL = os.getenv(
    "FLOW_BASE_URL",
    "https://zgsolucoes.flow.gp/Metadados.Api",
).rstrip("/")
FLOW_API_TOKEN = os.getenv("FLOW_API_TOKEN") or None
FLOW_ENABLED = _env_bool("FLOW_ENABLED", False)

# Daily point × Clockify reconciliation
HOURS_COMPETENCE_CLOSING_DAY = _env_day_of_month(
    "HOURS_COMPETENCE_CLOSING_DAY",
    25,
)
HOURS_RECONCILIATION_LOOKBACK_DAYS = _env_nonnegative_int(
    "HOURS_RECONCILIATION_LOOKBACK_DAYS",
    45,
)
HOURS_RECONCILIATION_TOLERANCE_MINUTES = _env_nonnegative_int(
    "HOURS_RECONCILIATION_TOLERANCE_MINUTES",
    15,
)
FLOW_RECONCILIATION_IGNORED_PERSON_IDS = _env_csv_set(
    "FLOW_RECONCILIATION_IGNORED_PERSON_IDS",
    "208",
)

# Operational runtime
ETL_AUTO_MIGRATE = _env_bool("ETL_AUTO_MIGRATE", True)

# Jira custom fields (instance-specific)
JIRA_SQUAD_FIELD = os.getenv("JIRA_SQUAD_FIELD", "customfield_10431")
JIRA_SPRINT_FIELD = os.getenv("JIRA_SPRINT_FIELD", "customfield_10010")
JIRA_CROSSING_FIELD = os.getenv("JIRA_CROSSING_FIELD", "customfield_10894")
