"""Conferência da cadeia de auditoria.

Recalcula cada elo a partir do que está gravado e compara com o hash registrado. Adulterar um
evento antigo muda o hash dele e, por consequência, quebra todos os seguintes — o verificador
aponta exatamente onde a cadeia deixou de fechar.

Puro: recebe os eventos já carregados, não consulta nada.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.audit.trilha import Contexto, calcular_hash, montar_payload
from app.models.auditoria import AuditEvent


@dataclass(frozen=True)
class Quebra:
    """Um ponto em que a cadeia não fecha."""

    evento_id: int
    posicao: int
    motivo: str

    def como_dict(self) -> dict:
        return {"evento_id": self.evento_id, "posicao": self.posicao, "motivo": self.motivo}


def hash_esperado(evento: AuditEvent, pt_uuid: str, hash_anterior: str | None) -> str:
    """Recalcula o hash de um evento a partir do conteúdo gravado."""
    payload = montar_payload(
        # Cada evento é conferido pelo formato com que nasceu — é isso que impede que
        # acrescentar um campo hoje invalide toda a trilha de ontem.
        versao=evento.versao_payload,
        pt_uuid=pt_uuid,
        tipo_evento=evento.tipo_evento,
        ator_id=evento.ator_id,
        estado_origem=evento.estado_origem,
        estado_destino=evento.estado_destino,
        motivo=evento.motivo,
        ocorrido_em=evento.ocorrido_em,
        hash_documento=evento.hash_documento,
        contexto=Contexto(
            dispositivo=evento.dispositivo,
            ip=evento.ip,
            geolocalizacao=evento.geolocalizacao,
        ),
        evento_compensado_id=evento.evento_compensado_id,
    )
    return calcular_hash(hash_anterior, payload)


def verificar_cadeia(eventos: Sequence[AuditEvent], pt_uuid: str) -> list[Quebra]:
    """Confere a cadeia inteira de uma PT, na ordem de inserção.

    Duas conferências por elo, porque falham por motivos diferentes: o `hash_anterior` gravado
    precisa apontar para o elo anterior de fato (detecta evento **removido** ou reordenado), e
    o `hash_evento` precisa bater com o conteúdo (detecta evento **alterado**).
    """
    quebras: list[Quebra] = []
    anterior: str | None = None

    for posicao, evento in enumerate(eventos):
        if evento.hash_anterior != anterior:
            quebras.append(
                Quebra(
                    evento_id=evento.id,
                    posicao=posicao,
                    motivo=(
                        "o elo anterior não confere: evento removido, reordenado ou inserido "
                        "fora de sequência"
                    ),
                )
            )

        recalculado = hash_esperado(evento, pt_uuid, evento.hash_anterior)
        if recalculado != evento.hash_evento:
            quebras.append(
                Quebra(
                    evento_id=evento.id,
                    posicao=posicao,
                    motivo="o conteúdo do evento não corresponde ao hash registrado",
                )
            )

        anterior = evento.hash_evento

    return quebras
