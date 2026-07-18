from dotenv import load_dotenv
import os

load_dotenv()

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

# Jira custom fields (instance-specific)
JIRA_SQUAD_FIELD = os.getenv("JIRA_SQUAD_FIELD", "customfield_10431")
JIRA_SPRINT_FIELD = os.getenv("JIRA_SPRINT_FIELD", "customfield_10010")
