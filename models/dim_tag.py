from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimTag(Base):
    """Clockify tag catalogue with a stable normalized lookup key."""

    __tablename__ = "dim_tag"

    tag_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(200))
    nome_normalizado: Mapped[str] = mapped_column(String(200), unique=True, index=True)
