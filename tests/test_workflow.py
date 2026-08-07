"""A máquina de estados em si — grafo puro, sem banco."""

import pytest

from app.models.enums import EstadoPT
from app.rules.pendencias import bloqueiam
from app.workflow.maquina import TRANSICOES, transicoes_de, validar_transicao


def test_o_caminho_declarado_e_aceito() -> None:
    assert validar_transicao(EstadoPT.RASCUNHO, EstadoPT.VALIDACAO) == []
    assert validar_transicao(EstadoPT.APROVACAO, EstadoPT.LIBERACAO) == []


@pytest.mark.parametrize(
    ("origem", "destino"),
    [
        (EstadoPT.RASCUNHO, EstadoPT.APROVACAO),  # pular três etapas
        (EstadoPT.RASCUNHO, EstadoPT.LIBERACAO),
        (EstadoPT.VALIDACAO, EstadoPT.EM_EXECUCAO),
        (EstadoPT.LIBERACAO, EstadoPT.RASCUNHO),  # voltar sem rejeição
    ],
)
def test_pular_etapa_nao_e_um_caso_especial_e_sim_um_passo_inexistente(
    origem: EstadoPT, destino: EstadoPT
) -> None:
    """Regra 6: o grafo não declara o atalho, então ele simplesmente não existe."""
    pendencias = validar_transicao(origem, destino)

    assert {p.codigo for p in pendencias} == {"transicao_invalida"}
    assert bloqueiam(pendencias)


def test_suspensa_so_nasce_de_em_execucao() -> None:
    origens = [
        estado
        for estado in EstadoPT
        if any(t.destino == EstadoPT.SUSPENSA for t in transicoes_de(estado))
    ]
    assert origens == [EstadoPT.EM_EXECUCAO]


def test_rejeitada_so_volta_para_rascunho() -> None:
    destinos = [t.destino for t in transicoes_de(EstadoPT.REJEITADA)]
    assert destinos == [EstadoPT.RASCUNHO]


def test_arquivada_e_terminal() -> None:
    assert transicoes_de(EstadoPT.ARQUIVADA) == ()
    assert bloqueiam(validar_transicao(EstadoPT.ARQUIVADA, EstadoPT.RASCUNHO))


def test_todo_estado_do_enum_esta_no_grafo_e_todo_destino_e_alcancavel() -> None:
    """Estado fora do grafo seria um beco sem saída silencioso."""
    assert set(TRANSICOES) == set(EstadoPT)

    alcancaveis = {t.destino for passos in TRANSICOES.values() for t in passos}
    assert alcancaveis == set(EstadoPT) - {EstadoPT.RASCUNHO} | {EstadoPT.RASCUNHO}


def test_liberacao_para_execucao_exige_risco_limpo() -> None:
    """O ponto em que a PT deixa de ser papel e vira gente exposta."""
    passo = next(t for t in transicoes_de(EstadoPT.LIBERACAO) if t.destino == EstadoPT.EM_EXECUCAO)
    retomada = next(
        t for t in transicoes_de(EstadoPT.SUSPENSA) if t.destino == EstadoPT.EM_EXECUCAO
    )

    assert passo.exige_risco_limpo
    assert retomada.exige_risco_limpo
