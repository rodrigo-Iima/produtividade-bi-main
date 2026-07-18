from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimPapelTag(Base):
    """Many-to-many role/tag matrix used to calculate focus."""

    __tablename__ = "dim_papel_tag"

    papel: Mapped[str] = mapped_column(String(100), primary_key=True)
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("dim_tag.tag_id"), primary_key=True
    )
    foco: Mapped[str] = mapped_column(String(200))
