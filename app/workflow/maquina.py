"""A máquina de estados da PT.

Grafo explícito e função pura: nenhuma transição existe por acidente, e nenhuma pode ser
pulada (regra 6). O que não está declarado aqui não acontece.
"""

from dataclasses import dataclass

from app.models.enums import EstadoPT, PapelAssinatura
from app.rules.pendencias import Pendencia, bloqueio


@dataclass(frozen=True)
class Transicao:
    """Um passo do fluxo: quem responde por ele, se assina, e se o risco precisa estar limpo."""

    destino: EstadoPT
    papel: PapelAssinatura
    exige_risco_limpo: bool = False
    # Nem todo passo é assinatura. Arquivar e devolver ao rascunho são atos administrativos:
    # exigem papel e ficam na trilha, mas não produzem assinatura no documento.
    assina: bool = True


# O fluxo inteiro, estado por estado. Ler esta tabela é ler o processo.
TRANSICOES: dict[EstadoPT, tuple[Transicao, ...]] = {
    EstadoPT.RASCUNHO: (
        Transicao(EstadoPT.VALIDACAO, PapelAssinatura.REQUISITANTE),
    ),
    EstadoPT.VALIDACAO: (
        Transicao(EstadoPT.ANALISE_SMS, PapelAssinatura.AREA_RESPONSAVEL),
        Transicao(EstadoPT.REJEITADA, PapelAssinatura.AREA_RESPONSAVEL),
    ),
    EstadoPT.ANALISE_SMS: (
        Transicao(EstadoPT.APROVACAO, PapelAssinatura.TECNICO_SEGURANCA),
        Transicao(EstadoPT.REJEITADA, PapelAssinatura.TECNICO_SEGURANCA),
    ),
    EstadoPT.APROVACAO: (
        Transicao(EstadoPT.LIBERACAO, PapelAssinatura.COORDENADOR),
        Transicao(EstadoPT.REJEITADA, PapelAssinatura.COORDENADOR),
    ),
    # A liberação é o ponto em que a PT deixa de ser papel e vira gente exposta: é aqui que o
    # motor de regras precisa estar limpo.
    EstadoPT.LIBERACAO: (
        Transicao(EstadoPT.EM_EXECUCAO, PapelAssinatura.EXECUTANTE, exige_risco_limpo=True),
    ),
    EstadoPT.EM_EXECUCAO: (
        Transicao(EstadoPT.ENCERRADA, PapelAssinatura.EXECUTANTE),
        # Suspender e retomar são eventos operacionais, e podem se repetir na mesma versão do
        # documento — daí não produzirem assinatura. Ficam na trilha com ator, momento,
        # contexto e hash, que é o que a regra 6 exige.
        Transicao(EstadoPT.SUSPENSA, PapelAssinatura.TECNICO_SEGURANCA, assina=False),
    ),
    # Retomar exige o mesmo crivo da liberação: o que suspendeu pode não ter sido resolvido.
    EstadoPT.SUSPENSA: (
        Transicao(
            EstadoPT.EM_EXECUCAO,
            PapelAssinatura.COORDENADOR,
            exige_risco_limpo=True,
            assina=False,
        ),
        Transicao(EstadoPT.ENCERRADA, PapelAssinatura.COORDENADOR),
    ),
    EstadoPT.ENCERRADA: (
        Transicao(EstadoPT.ARQUIVADA, PapelAssinatura.COORDENADOR, assina=False),
    ),
    # Devolver ao rascunho é do requisitante, e o serviço ainda exige que seja o dono da PT.
    EstadoPT.REJEITADA: (
        Transicao(EstadoPT.RASCUNHO, PapelAssinatura.REQUISITANTE, assina=False),
    ),
    EstadoPT.ARQUIVADA: (),
}

# Estados a partir dos quais o conteúdo da PT ainda pode ser corrigido.
ESTADOS_EDITAVEIS = frozenset({EstadoPT.RASCUNHO})


def transicoes_de(estado: EstadoPT) -> tuple[Transicao, ...]:
    """Passos possíveis a partir de um estado."""
    return TRANSICOES.get(estado, ())


def transicao_para(estado: EstadoPT, destino: EstadoPT) -> Transicao | None:
    """A transição declarada entre dois estados, ou `None` se ela não existe."""
    return next((t for t in transicoes_de(estado) if t.destino == destino), None)


def validar_transicao(origem: EstadoPT, destino: EstadoPT) -> list[Pendencia]:
    """Recusa qualquer passo que não esteja declarado no grafo.

    É assim que a regra 6 é cumprida: pular etapa não é um caso especial a tratar, é o
    resultado natural de o passo não existir.
    """
    if transicao_para(origem, destino) is not None:
        return []

    possiveis = [str(t.destino) for t in transicoes_de(origem)]
    detalhe = ", ".join(possiveis) if possiveis else "nenhum — é um estado final"
    return [
        bloqueio(
            "transicao_invalida",
            f"Não existe transição de {origem} para {destino}. A partir de {origem}: {detalhe}",
            campo="destino",
        )
    ]
