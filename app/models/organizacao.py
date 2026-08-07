"""Onde o trabalho acontece: unidade, área e equipamento."""

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import Criticidade, TipoUnidade
from app.models.tipos import TimestampMixin, enum_col


class Unidade(TimestampMixin, Base):
    """Plataforma, navio ou base. Raiz do escopo de tudo que é emitido a bordo."""

    __tablename__ = "unidade"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    identificador_operacional: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    tipo: Mapped[TipoUnidade] = mapped_column(enum_col(TipoUnidade), nullable=False)
    ativa: Mapped[bool] = mapped_column(default=True, nullable=False)

    areas: Mapped[list["Area"]] = relationship(
        back_populates="unidade", cascade="all, delete-orphan"
    )


class Area(TimestampMixin, Base):
    """Área operacional de uma unidade (praça de máquinas, convés, casario)."""

    __tablename__ = "area"
    __table_args__ = (UniqueConstraint("unidade_id", "codigo", name="uq_area_unidade_codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    unidade_id: Mapped[int] = mapped_column(
        ForeignKey("unidade.id", ondelete="CASCADE"), index=True, nullable=False
    )
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)

    unidade: Mapped[Unidade] = relationship(back_populates="areas")
    equipamentos: Mapped[list["Equipamento"]] = relationship(
        back_populates="area", cascade="all, delete-orphan"
    )


class Equipamento(TimestampMixin, Base):
    """Ativo físico identificado por TAG, sempre lotado em uma área."""

    __tablename__ = "equipamento"

    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int] = mapped_column(
        ForeignKey("area.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tag: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    descricao: Mapped[str] = mapped_column(String(200), nullable=False)
    criticidade: Mapped[Criticidade] = mapped_column(enum_col(Criticidade), nullable=False)

    area: Mapped[Area] = relationship(back_populates="equipamentos")
