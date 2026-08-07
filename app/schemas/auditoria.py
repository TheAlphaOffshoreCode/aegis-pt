"""Schemas de leitura da trilha e dos alertas.

Nenhum dos dois tem schema de escrita: evento de auditoria e alerta nascem no servidor, a
partir do que aconteceu. Aceitar um evento vindo do cliente seria aceitar trilha forjada.
"""

from datetime import datetime

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


class AlertaRead(ORMDatado):
    id: int
    tipo: str
    entidade: str
    entidade_id: int
    prazo: datetime | None
    nivel_escalonamento: int
    status: StatusAlerta
