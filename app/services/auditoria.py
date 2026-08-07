"""Consulta e compensação da trilha."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.documento import hash_do_documento
from app.audit.trilha import Contexto, registrar_evento
from app.audit.verificador import Quebra, verificar_cadeia
from app.models.auditoria import AuditEvent
from app.models.permissao import PermissaoTrabalho
from app.models.pessoa import Usuario
from app.rules.pendencias import ConflitoDeNegocio, bloqueio

TIPO_COMPENSACAO = "pt.compensacao"


def eventos_da_pt(db: Session, pt: PermissaoTrabalho) -> Sequence[AuditEvent]:
    """Trilha completa da PT, na ordem de inserção — que é a ordem da cadeia."""
    return db.scalars(
        select(AuditEvent).where(AuditEvent.pt_id == pt.id).order_by(AuditEvent.id)
    ).all()


def conferir(db: Session, pt: PermissaoTrabalho) -> tuple[Sequence[AuditEvent], list[Quebra]]:
    """Devolve a trilha e onde ela eventualmente deixa de fechar."""
    eventos = eventos_da_pt(db, pt)
    return eventos, verificar_cadeia(eventos, pt.uuid)


def compensar(
    db: Session,
    pt: PermissaoTrabalho,
    evento_id: int,
    ator: Usuario,
    motivo: str,
    contexto: Contexto = Contexto(),
) -> AuditEvent:
    """Corrige um registro sem tocar nele: acrescenta um evento que aponta para o original.

    É o único caminho de correção que a regra 4 admite. O evento errado continua lá, visível —
    trilha que some quando incomoda não é trilha.
    """
    original = db.get(AuditEvent, evento_id)
    if original is None or original.pt_id != pt.id:
        raise ConflitoDeNegocio(
            [bloqueio("evento_inexistente", "Evento não encontrado nesta PT", campo="evento_id")]
        )
    if original.tipo_evento == TIPO_COMPENSACAO:
        raise ConflitoDeNegocio(
            [
                bloqueio(
                    "compensacao_de_compensacao",
                    "Uma compensação não é corrigida por outra; registre um evento novo",
                    campo="evento_id",
                )
            ]
        )

    # O vínculo vai na criação: atribuí-lo depois deixaria o evento sujo na sessão, e o guard
    # de append-only recusaria — corretamente.
    evento = registrar_evento(
        db,
        pt=pt,
        tipo_evento=TIPO_COMPENSACAO,
        ator=ator,
        hash_documento=hash_do_documento(pt),
        motivo=motivo,
        contexto=contexto,
        evento_compensado_id=original.id,
    )
    db.commit()
    db.refresh(evento)
    return evento
