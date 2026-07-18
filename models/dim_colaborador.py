from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimColaborador(Base):
    """Dimension table for team members — role and squad from Clockify groups."""

    __tablename__ = "dim_colaborador"

    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)

    name: Mapped[str] = mapped_column(String(200))

    papel: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    squad_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("dim_squad.squad_id"), nullable=True, index=True
    )
