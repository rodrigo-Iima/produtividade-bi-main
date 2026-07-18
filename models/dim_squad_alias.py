from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimSquadAlias(Base):
    """Maps raw squad names from Jira or Clockify to a standard squad."""

    __tablename__ = "dim_squad_alias"

    origem: Mapped[str] = mapped_column(String(30), primary_key=True)
    nome_bruto: Mapped[str] = mapped_column(String(200), primary_key=True)
    squad_id: Mapped[int] = mapped_column(ForeignKey("dim_squad.squad_id"), index=True)
