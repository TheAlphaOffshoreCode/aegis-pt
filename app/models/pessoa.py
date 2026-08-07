"""Quem trabalha: usuário e suas certificações."""

from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import PerfilUsuario, TipoCertificacao
from app.models.tipos import TimestampMixin, UTCDateTime, enum_col


class Usuario(TimestampMixin, Base):
    """Pessoa com acesso ao sistema."""

    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    matricula: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    empresa: Mapped[str] = mapped_column(String(120), nullable=False)
    cargo: Mapped[str] = mapped_column(String(80), nullable=False)
    perfil: Mapped[PerfilUsuario] = mapped_column(enum_col(PerfilUsuario), nullable=False)
    ativo: Mapped[bool] = mapped_column(default=True, nullable=False)

    # Lotação. Nulo significa alcance global (auditor, admin) — é o que o escopo da regra 5
    # consulta antes de qualquer consulta ao banco.
    unidade_id: Mapped[int | None] = mapped_column(ForeignKey("unidade.id"), index=True)
    # Nunca a senha: só o hash Argon2. Vazio = usuário que ainda não pode entrar.
    senha_hash: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    ultimo_acesso: Mapped[datetime | None] = mapped_column(UTCDateTime)

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
