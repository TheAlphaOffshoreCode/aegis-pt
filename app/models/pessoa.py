"""Quem trabalha: usuário e suas certificações."""

from datetime import date

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import PerfilUsuario, TipoCertificacao
from app.models.tipos import TimestampMixin, enum_col


class Usuario(TimestampMixin, Base):
    """Pessoa com acesso ao sistema. Credencial e senha entram no L2."""

    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    matricula: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    empresa: Mapped[str] = mapped_column(String(120), nullable=False)
    cargo: Mapped[str] = mapped_column(String(80), nullable=False)
    perfil: Mapped[PerfilUsuario] = mapped_column(enum_col(PerfilUsuario), nullable=False)
    ativo: Mapped[bool] = mapped_column(default=True, nullable=False)

    certificacoes: Mapped[list["Certificacao"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan"
    )


class Certificacao(TimestampMixin, Base):
    """Habilitação normativa de um usuário.

    A conferência de validade é do motor de regras (L4): data vencida bloqueia a liberação,
    e essa decisão não pode nascer aqui nem sair de modelo de linguagem.
    """

    __tablename__ = "certificacao"
    __table_args__ = (
        UniqueConstraint("usuario_id", "tipo", "numero", name="uq_certificacao_usuario_tipo_numero"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuario.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tipo: Mapped[TipoCertificacao] = mapped_column(enum_col(TipoCertificacao), nullable=False)
    numero: Mapped[str] = mapped_column(String(60), nullable=False)
    emitida_em: Mapped[date] = mapped_column(Date, nullable=False)
    valida_ate: Mapped[date] = mapped_column(Date, index=True, nullable=False)

    usuario: Mapped[Usuario] = relationship(back_populates="certificacoes")
