"""Execução de uma transição de estado da PT.

Ordem das conferências importa: recusa-se o passo inexistente antes de olhar quem assina, e
quem assina antes de rodar o motor de risco. Assim a mensagem que volta é a do primeiro
problema real, e não a de um efeito colateral dele.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.audit.documento import diferencas, hash_do_documento, snapshot_da_pt
from app.audit.trilha import Contexto, registrar_evento
from app.models.enums import EstadoPT, PerfilUsuario
from app.models.permissao import Assinatura, PermissaoTrabalho, PTVersao
from app.models.pessoa import Usuario
from app.rules.motor import validar_assinatura
from app.rules.pendencias import ConflitoDeNegocio, Pendencia, bloqueiam, bloqueio
from app.services.permissoes import pendencias_da_pt
from app.workflow.maquina import Transicao, transicao_para, transicoes_de, validar_transicao


def transicoes_disponiveis(pt: PermissaoTrabalho, usuario: Usuario) -> list[dict]:
    """Passos possíveis a partir do estado atual, e se este usuário pode dar cada um.

    A tela precisa disso para não duplicar a máquina de estados no navegador — e regra de
    autorização duplicada no cliente é regra que diverge.
    """
    return [
        {
            "destino": t.destino,
            "papel": t.papel,
            "assina": t.assina,
            "permitida": not bloqueiam(_impedimentos_de_ator(pt, usuario, t)),
        }
        for t in transicoes_de(pt.estado)
    ]


def _impedimentos_de_ator(
    pt: PermissaoTrabalho, usuario: Usuario, transicao: Transicao
) -> list[Pendencia]:
    """Quem o usuário é, contra o que o passo exige."""
    pendencias = validar_assinatura(pt, usuario, transicao.papel)

    # Devolver ao rascunho é do dono do rascunho: qualquer requisitante da unidade passaria
    # só pela checagem de papel.
    if (
        transicao.destino == EstadoPT.RASCUNHO
        and usuario.perfil != PerfilUsuario.ADMIN
        and pt.requisitante_id != usuario.id
    ):
        pendencias.append(
            bloqueio(
                "nao_e_o_requisitante",
                "Só o requisitante pode devolver a PT ao rascunho",
                campo="destino",
            )
        )
    return pendencias


def _versionar(db: Session, pt: PermissaoTrabalho, autor: Usuario, motivo: str) -> None:
    """Congela o retrato da PT ao sair do rascunho.

    Reenvio depois de rejeição gera versão nova, e a unicidade por (pt, papel, versão) faz as
    assinaturas da versão anterior deixarem de valer sem apagar nada.
    """
    anterior = max(pt.versoes, key=lambda v: v.versao, default=None)
    pt.versao = (anterior.versao + 1) if anterior else 1
    db.flush()

    atual = snapshot_da_pt(pt)
    db.add(
        PTVersao(
            pt_id=pt.id,
            versao=pt.versao,
            snapshot=atual,
            diff=diferencas(anterior.snapshot, atual) if anterior else {},
            autor_id=autor.id,
            motivo=motivo,
        )
    )
    db.flush()


def executar_transicao(
    db: Session,
    pt: PermissaoTrabalho,
    destino: EstadoPT,
    ator: Usuario,
    *,
    motivo: str | None = None,
    visto_em: datetime | None = None,
    contexto: Contexto = Contexto(),
) -> PermissaoTrabalho:
    """Move a PT de estado, assinando, versionando e registrando na trilha."""
    # Assinar é declarar que se leu o documento. Se ele mudou entre a leitura e a assinatura,
    # a assinatura seria sobre outra coisa — e o hash gravado na trilha registraria uma
    # concordância que nunca houve.
    if visto_em is not None and visto_em != pt.atualizado_em:
        raise ConflitoDeNegocio(
            [
                bloqueio(
                    "documento_alterado",
                    f"A PT foi alterada em {pt.atualizado_em:%d/%m/%Y %H:%M:%S} UTC, depois da "
                    "versão que você leu. Recarregue antes de assinar.",
                )
            ]
        )

    pendencias = validar_transicao(pt.estado, destino)
    if bloqueiam(pendencias):
        raise ConflitoDeNegocio(bloqueiam(pendencias))

    transicao = transicao_para(pt.estado, destino)
    pendencias = _impedimentos_de_ator(pt, ator, transicao)

    # Rejeitar ou suspender sem dizer por quê não deixa ninguém corrigir nada, e é o registro
    # que a investigação de incidente vai procurar primeiro.
    if destino in (EstadoPT.REJEITADA, EstadoPT.SUSPENSA) and not (motivo or "").strip():
        pendencias.append(
            bloqueio(
                "motivo_obrigatorio",
                f"Mover a PT para {destino} exige um motivo registrado",
                campo="motivo",
            )
        )

    if bloqueiam(pendencias):
        raise ConflitoDeNegocio(bloqueiam(pendencias))

    if transicao.exige_risco_limpo:
        risco = bloqueiam(pendencias_da_pt(db, pt))
        if risco:
            raise ConflitoDeNegocio(risco)

    origem = pt.estado
    if origem == EstadoPT.RASCUNHO:
        _versionar(db, pt, ator, motivo or "Envio para validação")

    # Calculado depois do versionamento: o retrato assinado é o da versão que está indo adiante.
    hash_documento = hash_do_documento(pt)

    if transicao.assina:
        db.add(
            Assinatura(
                pt_id=pt.id,
                usuario_id=ator.id,
                papel=transicao.papel,
                estado_destino=destino,
                versao_pt=pt.versao,
                hash_documento=hash_documento,
            )
        )

    pt.estado = destino
    registrar_evento(
        db,
        pt=pt,
        tipo_evento=f"pt.transicao.{destino.lower()}",
        ator=ator,
        hash_documento=hash_documento,
        estado_origem=origem,
        estado_destino=destino,
        motivo=motivo,
        contexto=contexto,
    )

    db.commit()
    db.refresh(pt)
    return pt
