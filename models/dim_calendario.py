from datetime import date

from sqlalchemy import Boolean, Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class DimCalendario(Base):
    """Calendar dimension table — one row per date."""

    __tablename__ = "dim_calendario"

    data: Mapped[date] = mapped_column(Date, primary_key=True)

    ano: Mapped[int] = mapped_column(Integer)

    mes_numero: Mapped[int] = mapped_column(Integer)

    mes_nome: Mapped[str] = mapped_column(String(20))

    dia_semana: Mapped[str] = mapped_column(String(20))

    dia_util: Mapped[bool] = mapped_column(Boolean)

    dia_do_mes: Mapped[int] = mapped_column(Integer)
