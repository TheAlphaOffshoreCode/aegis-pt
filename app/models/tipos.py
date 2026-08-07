"""Tipos e mixins compartilhados por todos os modelos."""

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column


def agora_utc() -> datetime:
    """Instante atual em UTC. Uma unidade offshore cruza fuso; hora local não audita nada."""
    return datetime.now(UTC)


def enum_col(enum_cls: type[StrEnum]) -> Enum:
    """Coluna de enum portável entre SQLite e PostgreSQL: VARCHAR com CHECK nomeado.

    Sem `values_callable` o SQLAlchemy grava o *nome* do membro (`NR_33`) e o banco passa a
    divergir do que a API e a tela mostram (`NR-33`).
    """
    return Enum(
        enum_cls,
        native_enum=False,
        values_callable=lambda cls: [membro.value for membro in cls],
        name=enum_cls.__name__.lower(),
        length=40,
        validate_strings=True,
    )


class TimestampMixin:
    """`criado_em` e `atualizado_em` em UTC, mantidos pelo ORM."""

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora_utc, nullable=False
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora_utc, onupdate=agora_utc, nullable=False
    )
