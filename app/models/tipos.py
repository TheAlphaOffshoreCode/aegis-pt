"""Tipos e mixins compartilhados por todos os modelos."""

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column


def agora_utc() -> datetime:
    """Instante atual em UTC. Uma unidade offshore cruza fuso; hora local não audita nada."""
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Data e hora que sempre volta do banco em UTC, com fuso.

    O SQLite não armazena offset: uma coluna `DateTime(timezone=True)` devolve datetime
    *naive* lá e *aware* no PostgreSQL. Comparar o valor lido com `agora_utc()` passa em um
    banco e levanta `TypeError` no outro — o defeito que só aparece no ambiente que não é o
    seu. Normalizar na borda do banco resolve para todo consumidor de uma vez.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:  # noqa: ANN001
        if value is None:
            return None
        # Naive que chega da API é tratado como UTC. Exigir offset explícito é decisão do
        # contrato HTTP, não do banco.
        return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:  # noqa: ANN001
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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
        UTCDateTime, default=agora_utc, nullable=False
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        UTCDateTime, default=agora_utc, onupdate=agora_utc, nullable=False
    )
