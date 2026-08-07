"""Schemas de leitura da trilha e dos alertas.

Nenhum dos dois tem schema de escrita: evento de auditoria e alerta nascem no servidor, a
partir do que aconteceu. Aceitar um evento vindo do cliente seria aceitar trilha forjada.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import EstadoPT, PerfilUsuario, StatusAlerta
from app.schemas.base import ORMDatado, ORMSchema


class AuditEventRead(ORMSchema):
    id: int
    pt_id: int | None
    ator_id: int | None
    perfil_ator: PerfilUsuario | None
    tipo_evento: str
    estado_origem: EstadoPT | None
    estado_destino: EstadoPT | None
    motivo: str | None
    ocorrido_em: datetime
    dispositivo: str | None
    ip: str | None
    geolocalizacao: str | None
    hash_documento: str | None
    hash_anterior: str | None
    hash_evento: str
    evento_compensado_id: int | None


class QuebraRead(BaseModel):
    """Onde a cadeia deixou de fechar."""

    evento_id: int
    posicao: int
    motivo: str


class TrilhaRead(BaseModel):
    """A trilha da PT e o resultado da conferência de integridade."""

    pt_id: int
    numero: str
    integra: bool
    quebras: list[QuebraRead]
    eventos: list[AuditEventRead]


class CompensacaoRequest(BaseModel):
    """Correção de um registro. Nunca altera o original — cria um evento que o referencia."""

    motivo: str = Field(min_length=1, max_length=2000)
    geolocalizacao: str | None = Field(default=None, max_length=80)


class AlertaRead(ORMDatado):
    id: int
    tipo: str
    entidade: str
    entidade_id: int
    prazo: datetime | None
    nivel_escalonamento: int
    status: StatusAlerta
