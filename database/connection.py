from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import (
    DATABASE_URL as RAILWAY_DATABASE_URL,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    POSTGRES_SSLMODE,
)


def _resolve_database_url() -> str:
    """Use Railway's DATABASE_URL or the local POSTGRES_* fallback."""
    if RAILWAY_DATABASE_URL:
        return RAILWAY_DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1).replace(
            "postgresql://", "postgresql+psycopg2://", 1
        )

    values = {
        "POSTGRES_HOST": DB_HOST,
        "POSTGRES_PORT": DB_PORT,
        "POSTGRES_DB": DB_NAME,
        "POSTGRES_USER": DB_USER,
        "POSTGRES_PASSWORD": DB_PASSWORD,
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "Configuração PostgreSQL incompleta. Defina DATABASE_URL ou: "
            + ", ".join(missing)
        )

    return (
        "postgresql+psycopg2://"
        f"{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )


DATABASE_URL = _resolve_database_url()
connect_args = {"sslmode": POSTGRES_SSLMODE} if POSTGRES_SSLMODE else {}

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(bind=engine)
