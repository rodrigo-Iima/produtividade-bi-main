from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimStatus(Base):
    """Jira status grouping used by downstream queries."""

    __tablename__ = "dim_status"

    status_original: Mapped[str] = mapped_column(String(100), primary_key=True)
    status_agrupado: Mapped[str] = mapped_column(String(50))
