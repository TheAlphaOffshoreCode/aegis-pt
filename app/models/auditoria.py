"""Trilha de auditoria e alertas."""

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.audit.formato import VERSAO_PAYLOAD
from app.database import Base, SessionLocal
from app.models.enums import EstadoPT, PerfilUsuario, StatusAlerta
from app.models.tipos import TimestampMixin, UTCDateTime, agora_utc, enum_col


class AuditEvent(Base):
    """Evento append-only. A cadeia de hash e o verificador são do L6.

    `pt_id` usa RESTRICT de propósito: apagar uma PT que já tem trilha teria de apagar a
    prova junto, e trilha que some quando incomoda não é trilha.
    """

    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    pt_id: Mapped[int | None] = mapped_column(
        ForeignKey("permissao_trabalho.id", ondelete="RESTRICT"), index=True
    )
    ator_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), index=True)
    perfil_ator: Mapped[PerfilUsuario | None] = mapped_column(enum_col(PerfilUsuario))
    # Texto livre, e não enum: o catálogo de eventos cresce a cada loop, e um CHECK
    # exigiria migration para cada tipo novo de evento auditado.
    tipo_evento: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    estado_origem: Mapped[EstadoPT | None] = mapped_column(enum_col(EstadoPT))
    estado_destino: Mapped[EstadoPT | None] = mapped_column(enum_col(EstadoPT))
    motivo: Mapped[str | None] = mapped_column(Text)

    ocorrido_em: Mapped[datetime] = mapped_column(
        UTCDateTime, default=agora_utc, index=True, nullable=False
    )
    dispositivo: Mapped[str | None] = mapped_column(String(120))
    ip: Mapped[str | None] = mapped_column(String(45))
    geolocalizacao: Mapped[str | None] = mapped_column(String(80))

    hash_documento: Mapped[str | None] = mapped_column(String(64))
    hash_anterior: Mapped[str | None] = mapped_column(String(64))
    hash_evento: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Formato do payload com que este evento foi selado. Cada evento é conferido pelo formato
    # com que nasceu, senão acrescentar um campo invalidaria toda a trilha anterior.
    versao_payload: Mapped[int] = mapped_column(
        default=VERSAO_PAYLOAD, server_default="1", nullable=False
    )
    # Correção nunca apaga: aponta para o evento que está compensando.
    evento_compensado_id: Mapped[int | None] = mapped_column(ForeignKey("audit_event.id"))

    evento_compensado: Mapped["AuditEvent | None"] = relationship(remote_side=[id])


class TrilhaImutavel(Exception):
    """Tentativa de alterar ou apagar um evento de auditoria."""


# Registrado na `SessionLocal`, e não na classe `Session`: a mesma armadilha do
# `PRAGMA foreign_keys` no L0 — listener na classe alcançaria qualquer sessão do processo.
@event.listens_for(SessionLocal, "before_flush")
def _trilha_e_append_only(session, contexto_do_flush, instancias) -> None:  # noqa: ANN001
    """Regra 4 provada, e não apenas escrita na documentação.

    Sem isto, "append-only" depende de todo mundo lembrar. Uma correção é um evento novo
    apontando para o original em `evento_compensado_id`.
    """
    alterados = [obj for obj in session.dirty if isinstance(obj, AuditEvent)]
    apagados = [obj for obj in session.deleted if isinstance(obj, AuditEvent)]
    if alterados or apagados:
        raise TrilhaImutavel(
            "audit_event é append-only: use um evento compensatório em vez de alterar ou apagar"
        )


class Alerta(TimestampMixin, Base):
    """Pendência com prazo e escalonamento. Os disparos e regras de escalada são do L11."""

    __tablename__ = "alerta"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Mesma razão do `tipo_evento`: catálogo aberto, definido pelas regras do L11.
    tipo: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    entidade: Mapped[str] = mapped_column(String(40), nullable=False)
    entidade_id: Mapped[int] = mapped_column(nullable=False)
    prazo: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    nivel_escalonamento: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[StatusAlerta] = mapped_column(
        enum_col(StatusAlerta), default=StatusAlerta.ABERTO, index=True, nullable=False
    )
