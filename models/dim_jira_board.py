from typing import Optional

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimJiraBoard(Base):
    """Jira Agile boards used as the source of quick-filter definitions."""

    __tablename__ = "dim_jira_board"

    board_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    board_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
