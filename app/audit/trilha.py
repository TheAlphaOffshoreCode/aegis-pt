"""Escrita da trilha append-only.

A cadeia nasce aqui, e não no L6, por necessidade: a regra 6 diz que nenhuma transição ocorre
sem ator, momento, contexto e hash do documento. Gravar transição agora e encadear depois
significaria auditar um passado que não foi guardado — e reconstruir cadeia é caro e frágil.

Ao L6 ficam o verificador de integridade, a API de consulta e o evento compensatório.

Só há INSERT neste módulo. Nenhum caminho do sistema faz `UPDATE` ou `DELETE` em `audit_event`
(regra 4).
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.formato import VERSAO_PAYLOAD
from app.models.auditoria import AuditEvent
from app.models.enums import EstadoPT
from app.models.permissao import PermissaoTrabalho
from app.models.pessoa import Usuario
from app.models.tipos import agora_utc


@dataclass(frozen=True)
class Contexto:
    """De onde a ação partiu. Vazio é aceitável; mentira não — por isso nada tem default falso."""

    dispositivo: str | None = None
    ip: str | None = None
    geolocalizacao: str | None = None


def montar_payload(
    *,
    pt_uuid: str,
    tipo_evento: str,
    ator_id: int | None,
    estado_origem: EstadoPT | None,
    estado_destino: EstadoPT | None,
    motivo: str | None,
    ocorrido_em: datetime,
    hash_documento: str | None,
    contexto: "Contexto",
    evento_compensado_id: int | None = None,
    versao: int = VERSAO_PAYLOAD,
) -> str:
    """Forma canônica do evento, no formato da versão indicada.

    Uma função só, usada na escrita e na verificação. Se a conferência montasse o payload por
    conta própria, qualquer divergência entre as duas apontaria adulteração onde não houve — e
    um verificador que dá alarme falso é pior que nenhum.
    """
    payload = {
        "pt_uuid": pt_uuid,
        "tipo_evento": tipo_evento,
        "ator_id": ator_id,
        "estado_origem": None if estado_origem is None else str(estado_origem),
        "estado_destino": None if estado_destino is None else str(estado_destino),
        "motivo": motivo,
        "ocorrido_em": ocorrido_em.isoformat(),
        "hash_documento": hash_documento,
        "contexto": asdict(contexto),
    }
    if versao >= 2:
        # Entra no hash: sem isso, o vínculo de uma compensação com o evento que ela corrige
        # poderia ser trocado sem quebrar a cadeia.
        payload["evento_compensado_id"] = evento_compensado_id
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def calcular_hash(hash_anterior: str | None, payload: str) -> str:
    """`hash_evento = H(hash_anterior + payload)`."""
    return hashlib.sha256(f"{hash_anterior or ''}{payload}".encode("utf-8")).hexdigest()


def _ultimo_hash(db: Session, pt_id: int) -> str | None:
    return db.scalar(
        select(AuditEvent.hash_evento)
        .where(AuditEvent.pt_id == pt_id)
        .order_by(AuditEvent.id.desc())
        .limit(1)
    )


def registrar_evento(
    db: Session,
    *,
    pt: PermissaoTrabalho,
    tipo_evento: str,
    ator: Usuario | None,
    hash_documento: str,
    estado_origem: EstadoPT | None = None,
    estado_destino: EstadoPT | None = None,
    motivo: str | None = None,
    contexto: Contexto = Contexto(),
    evento_compensado_id: int | None = None,
) -> AuditEvent:
    """Acrescenta um elo à cadeia da PT. Nunca altera nada — só insere.

    `hash_evento = H(hash_anterior + payload)`: adulterar um evento antigo quebra todos os
    hashes seguintes, e é isso que o verificador do L6 vai procurar.
    """
    ocorrido_em = agora_utc()
    hash_anterior = _ultimo_hash(db, pt.id)

    payload = montar_payload(
        pt_uuid=pt.uuid,
        tipo_evento=tipo_evento,
        ator_id=None if ator is None else ator.id,
        estado_origem=estado_origem,
        estado_destino=estado_destino,
        motivo=motivo,
        ocorrido_em=ocorrido_em,
        hash_documento=hash_documento,
        contexto=contexto,
        evento_compensado_id=evento_compensado_id,
    )
    hash_evento = calcular_hash(hash_anterior, payload)

    evento = AuditEvent(
        pt_id=pt.id,
        ator_id=None if ator is None else ator.id,
        perfil_ator=None if ator is None else ator.perfil,
        tipo_evento=tipo_evento,
        estado_origem=estado_origem,
        estado_destino=estado_destino,
        motivo=motivo,
        ocorrido_em=ocorrido_em,
        dispositivo=contexto.dispositivo,
        ip=contexto.ip,
        geolocalizacao=contexto.geolocalizacao,
        hash_documento=hash_documento,
        hash_anterior=hash_anterior,
        hash_evento=hash_evento,
        evento_compensado_id=evento_compensado_id,
    )
    db.add(evento)
    db.flush()
    return evento
