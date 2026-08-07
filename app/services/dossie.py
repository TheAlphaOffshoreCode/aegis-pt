"""Dossiê da PT: o documento inteiro, com o que aconteceu com ele.

Nada é calculado aqui. O dossiê **compõe** o que os loops anteriores já produzem — versões,
assinaturas, anexos, trilha conferida e o veredito do motor de regras. É o retrato que uma
investigação de incidente pede, e por isso carrega a integridade da trilha junto: um histórico
que não diz se foi adulterado não serve como prova.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.permissao import Assinatura, PermissaoTrabalho, PTVersao
from app.services import auditoria, permissoes


def versoes_da_pt(db: Session, pt: PermissaoTrabalho) -> Sequence[PTVersao]:
    """Histórico de versões, da mais antiga para a mais nova."""
    return db.scalars(
        select(PTVersao).where(PTVersao.pt_id == pt.id).order_by(PTVersao.versao)
    ).all()


def montar(db: Session, pt: PermissaoTrabalho) -> dict:
    """Reúne tudo o que existe sobre uma PT."""
    eventos, quebras = auditoria.conferir(db, pt)
    assinaturas = db.scalars(
        select(Assinatura).where(Assinatura.pt_id == pt.id).order_by(Assinatura.id)
    ).all()
    pendencias = permissoes.pendencias_da_pt(db, pt)

    return {
        "pt": pt,
        "versoes": versoes_da_pt(db, pt),
        "assinaturas": assinaturas,
        "anexos": pt.anexos,
        "equipe": pt.equipe,
        "eventos": eventos,
        "trilha_integra": not quebras,
        "quebras": [q.como_dict() for q in quebras],
        "pendencias": [p.como_dict() for p in pendencias],
    }
