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

# Operational runtime
ETL_AUTO_MIGRATE = _env_bool("ETL_AUTO_MIGRATE", True)

# Jira custom fields (instance-specific)
JIRA_SQUAD_FIELD = os.getenv("JIRA_SQUAD_FIELD", "customfield_10431")
JIRA_SPRINT_FIELD = os.getenv("JIRA_SPRINT_FIELD", "customfield_10010")
JIRA_CROSSING_FIELD = os.getenv("JIRA_CROSSING_FIELD", "customfield_10894")
