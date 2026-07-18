from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimSquad(Base):
    """Canonical standardized squad dimension."""

    __tablename__ = "dim_squad"

    squad_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    nome: Mapped[str] = mapped_column(String(200), unique=True, index=True)
