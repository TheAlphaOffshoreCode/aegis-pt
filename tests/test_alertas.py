"""Alertas e indicadores: quando existem, para quem sobem, e quem os enxerga."""

import re
from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sincronizar_alertas
from app.models import Alerta, Area, ModeloPT, PermissaoTrabalho, Unidade, Usuario
from app.models.enums import (
    EstadoPT,
    PerfilUsuario,
    StatusAlerta,
    TipoCertificacao,
    TipoTrabalho,
    TipoUnidade,
)
from app.models.pessoa import Certificacao
from app.models.tipos import agora_utc
from app.rules import alertas as regras
from app.services import alertas, indicadores

HORAS_DE_UM_NIVEL = 8


@pytest.fixture
def cenario(
    db: Session, criar_usuario: Callable[..., Usuario],
    client: TestClient, autenticar: Callable[[str], dict[str, str]],
) -> dict:
    """Duas unidades, uma PT em execução em cada, e gente lotada nas duas."""
    alfa = Unidade(nome="FPSO Alfa", identificador_operacional="FPSO-A", tipo=TipoUnidade.FPSO)
    beta = Unidade(nome="FPSO Beta", identificador_operacional="FPSO-B", tipo=TipoUnidade.FPSO)
    db.add_all([alfa, beta])
    db.flush()
    area_alfa = Area(unidade_id=alfa.id, nome="Convés", codigo="CV")
    area_beta = Area(unidade_id=beta.id, nome="Convés", codigo="CV")
    modelo = ModeloPT(tipo_trabalho=TipoTrabalho.TRABALHO_A_QUENTE, nome="quente", campos=[])
    db.add_all([area_alfa, area_beta, modelo])
    db.commit()

    de_alfa = criar_usuario(matricula="70001", unidade_id=alfa.id)
    de_beta = criar_usuario(matricula="70002", unidade_id=beta.id)
    coordenador = criar_usuario(
        matricula="70003", perfil=PerfilUsuario.COORDENADOR, unidade_id=alfa.id
    )
    inicio = agora_utc()

    return {
        "alfa": alfa, "beta": beta,
        "area_alfa": area_alfa, "area_beta": area_beta,
        "modelo": modelo,
        "de_alfa": de_alfa, "de_beta": de_beta, "coordenador": coordenador,
        "cabecalho_alfa": autenticar("70001"),
        "cabecalho_beta": autenticar("70002"),
        "cabecalho_coordenador": autenticar("70003"),
        "inicio": inicio,
    }


def criar_pt(
    db: Session, cenario: dict, *, estado: EstadoPT, unidade: str = "alfa",
    valida_de: datetime | None = None, valida_ate: datetime | None = None, numero: str = "PT-2026-0001",
) -> PermissaoTrabalho:
    """Uma PT posta diretamente no estado desejado — aqui o alvo é o alerta, não o fluxo."""
    inicio = valida_de or cenario["inicio"]
    pt = PermissaoTrabalho(
        numero=numero,
        tipo_trabalho=TipoTrabalho.TRABALHO_A_QUENTE,
        estado=estado,
        modelo_pt_id=cenario["modelo"].id,
        unidade_id=cenario[unidade].id,
        area_id=cenario[f"area_{unidade}"].id,
        requisitante_id=cenario["de_alfa"].id,
        descricao="Solda em suporte",
        valida_de=inicio,
        valida_ate=valida_ate or (inicio + timedelta(hours=8)),
    )
    db.add(pt)
    db.commit()
    return pt


# --- a escada, como função pura ------------------------------------------------------------


def test_nivel_zero_antes_do_prazo() -> None:
    prazo = agora_utc() + timedelta(hours=1)

    assert regras.nivel_de_escalonamento(prazo, agora_utc()) == 0


def test_sobe_um_nivel_por_intervalo_vencido() -> None:
    prazo = agora_utc()

    assert regras.nivel_de_escalonamento(prazo, prazo + timedelta(hours=1)) == 0
    assert regras.nivel_de_escalonamento(prazo, prazo + timedelta(hours=HORAS_DE_UM_NIVEL)) == 1
    assert (
        regras.nivel_de_escalonamento(prazo, prazo + timedelta(hours=2 * HORAS_DE_UM_NIVEL)) == 2
    )


def test_o_ultimo_nivel_e_teto() -> None:
    """Acima do OIM não há para quem escalar a bordo — o nível para de subir."""
    prazo = agora_utc()

    assert regras.nivel_de_escalonamento(prazo, prazo + timedelta(days=30)) == 2
    assert regras.responsavel_do_nivel(2) == PerfilUsuario.OIM
    assert regras.responsavel_do_nivel(99) == PerfilUsuario.OIM


def test_a_escada_vai_do_requisitante_ao_oim() -> None:
    assert regras.responsavel_do_nivel(0) == PerfilUsuario.REQUISITANTE
    assert regras.responsavel_do_nivel(1) == PerfilUsuario.COORDENADOR


# --- as condições ---------------------------------------------------------------------------


def test_pt_em_execucao_com_janela_encerrada_gera_alerta_critico(
    db: Session, cenario: dict
) -> None:
    """O caso que mais importa: gente trabalhando com a autorização vencida."""
    pt = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO)
    depois = pt.valida_ate + timedelta(minutes=1)

    condicoes = regras.condicoes_das_pts([pt], depois)

    assert [c.tipo for c in condicoes] == ["pt_vencida_em_execucao"]
    assert condicoes[0].prazo == pt.valida_ate


def test_vencendo_e_vencida_nao_convivem(db: Session, cenario: dict) -> None:
    """Uma janela que já fechou não é 'quase fechando' — os dois alertas se excluem."""
    pt = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO)

    antes = regras.condicoes_das_pts([pt], pt.valida_ate - timedelta(hours=1))
    depois = regras.condicoes_das_pts([pt], pt.valida_ate + timedelta(hours=1))

    assert [c.tipo for c in antes] == ["pt_vencendo"]
    assert [c.tipo for c in depois] == ["pt_vencida_em_execucao"]


def test_pt_recem_liberada_nao_gera_alerta(db: Session, cenario: dict) -> None:
    pt = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO)

    assert regras.condicoes_das_pts([pt], pt.valida_de) == []


def test_pt_parada_na_aprovacao_vira_alerta(db: Session, cenario: dict) -> None:
    pt = criar_pt(db, cenario, estado=EstadoPT.ANALISE_SMS)

    dentro = regras.condicoes_das_pts([pt], pt.atualizado_em + timedelta(hours=23))
    fora = regras.condicoes_das_pts([pt], pt.atualizado_em + timedelta(hours=25))

    assert dentro == []
    assert [c.tipo for c in fora] == ["pt_parada"]


def test_certificacao_a_vencer_gera_um_alerta_por_certificacao(
    db: Session, cenario: dict
) -> None:
    """Quem tem duas habilitações vencendo tem dois problemas, com datas diferentes."""
    hoje = agora_utc().date()
    usuario = cenario["de_alfa"]
    db.add_all([
        Certificacao(usuario_id=usuario.id, tipo=TipoCertificacao.NR_33, numero="A1",
                     emitida_em=hoje - timedelta(days=365), valida_ate=hoje + timedelta(days=10)),
        Certificacao(usuario_id=usuario.id, tipo=TipoCertificacao.NR_35, numero="A2",
                     emitida_em=hoje - timedelta(days=365), valida_ate=hoje + timedelta(days=20)),
        Certificacao(usuario_id=usuario.id, tipo=TipoCertificacao.NR_10, numero="A3",
                     emitida_em=hoje - timedelta(days=365), valida_ate=hoje + timedelta(days=90)),
    ])
    db.commit()

    condicoes = regras.condicoes_das_certificacoes(
        db.scalars(select(Certificacao)).all(), agora_utc()
    )

    assert len(condicoes) == 2
    assert len({c.entidade_id for c in condicoes}) == 2
    assert all(c.entidade == "certificacao" for c in condicoes)


def test_certificacao_ja_vencida_nao_e_anunciada_como_a_vencer(
    db: Session, cenario: dict
) -> None:
    """Achado de rodar de verdade: o seed tem uma NR-35 vencida, e o alerta dizia
    "certificacao_a_vencer ... vence em 23/06/2026" — data passada, verbo no futuro.

    Vencida e a vencer são coisas diferentes, e o motor do L4 já as separa. O alerta passou a
    usar o mesmo vocabulário.
    """
    hoje = agora_utc().date()
    usuario = cenario["de_alfa"]
    db.add_all([
        Certificacao(usuario_id=usuario.id, tipo=TipoCertificacao.NR_33, numero="V1",
                     emitida_em=hoje - timedelta(days=800), valida_ate=hoje - timedelta(days=40)),
        Certificacao(usuario_id=usuario.id, tipo=TipoCertificacao.NR_35, numero="V2",
                     emitida_em=hoje - timedelta(days=365), valida_ate=hoje + timedelta(days=10)),
    ])
    db.commit()

    por_tipo = {
        c.tipo: c
        for c in regras.condicoes_das_certificacoes(
            db.scalars(select(Certificacao)).all(), agora_utc()
        )
    }

    assert set(por_tipo) == {"certificacao_vencida", "certificacao_a_vencer"}
    assert "venceu em" in por_tipo["certificacao_vencida"].mensagem
    assert "vence em" in por_tipo["certificacao_a_vencer"].mensagem


def test_certificacao_de_quem_nao_tem_lotacao_nao_vira_alerta(
    db: Session, cenario: dict, criar_usuario: Callable[..., Usuario]
) -> None:
    """Sem unidade não há escopo — e alerta que ninguém enxerga é pior que nenhum."""
    sem_lotacao = criar_usuario(matricula="70009", unidade_id=None)
    hoje = agora_utc().date()
    db.add(
        Certificacao(usuario_id=sem_lotacao.id, tipo=TipoCertificacao.NR_33, numero="B1",
                     emitida_em=hoje, valida_ate=hoje + timedelta(days=5))
    )
    db.commit()

    condicoes = regras.condicoes_das_certificacoes(
        db.scalars(select(Certificacao)).all(), agora_utc()
    )

    assert condicoes == []


# --- sincronização --------------------------------------------------------------------------


def test_sincronizar_e_idempotente(db: Session, cenario: dict) -> None:
    """Rodar de novo no mesmo instante não abre nem escala nada. É o que permite um cron."""
    pt = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO)
    momento = pt.valida_ate + timedelta(hours=1)

    primeira = alertas.sincronizar(db, momento)
    segunda = alertas.sincronizar(db, momento)

    assert primeira.abertos == 1
    assert (segunda.abertos, segunda.escalonados, segunda.resolvidos) == (0, 0, 0)
    assert len(db.scalars(select(Alerta)).all()) == 1


def test_o_alerta_sobe_de_nivel_com_o_tempo(db: Session, cenario: dict) -> None:
    pt = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO)
    alertas.sincronizar(db, pt.valida_ate + timedelta(minutes=1))

    resultado = alertas.sincronizar(db, pt.valida_ate + timedelta(hours=HORAS_DE_UM_NIVEL))

    alerta = db.scalars(select(Alerta)).one()
    assert resultado.escalonados == 1
    assert alerta.nivel_escalonamento == 1
    assert alerta.status == StatusAlerta.ESCALONADO


def test_o_alerta_e_resolvido_quando_a_condicao_some(db: Session, cenario: dict) -> None:
    """Resolvido, não apagado: sumir sem rastro esconderia que o problema existiu."""
    pt = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO)
    momento = pt.valida_ate + timedelta(hours=1)
    alertas.sincronizar(db, momento)

    pt.estado = EstadoPT.ENCERRADA
    db.commit()
    resultado = alertas.sincronizar(db, momento)

    alerta = db.scalars(select(Alerta)).one()
    assert resultado.resolvidos == 1
    assert alerta.status == StatusAlerta.RESOLVIDO


def test_a_data_de_abertura_nao_se_mexe_quando_o_alerta_escala(
    db: Session, cenario: dict
) -> None:
    """A mensagem acompanha o estado; `criado_em` é desde quando dói, e não muda."""
    pt = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO)
    alertas.sincronizar(db, pt.valida_ate + timedelta(minutes=1))
    db.expire_all()
    abertura = db.scalars(select(Alerta)).one().criado_em

    alertas.sincronizar(db, pt.valida_ate + timedelta(hours=HORAS_DE_UM_NIVEL))
    db.expire_all()

    assert db.scalars(select(Alerta)).one().criado_em == abertura


def test_rascunho_e_arquivada_nao_geram_alerta(db: Session, cenario: dict) -> None:
    criar_pt(db, cenario, estado=EstadoPT.RASCUNHO, numero="PT-2026-0001")
    criar_pt(db, cenario, estado=EstadoPT.ARQUIVADA, numero="PT-2026-0002")

    alertas.sincronizar(db, agora_utc() + timedelta(days=30))

    assert db.scalars(select(Alerta)).all() == []


# --- escopo (regra 5) -----------------------------------------------------------------------


def test_alerta_de_outra_unidade_nao_aparece(db: Session, cenario: dict) -> None:
    pt = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO, unidade="alfa")
    alertas.sincronizar(db, pt.valida_ate + timedelta(hours=1))

    do_alfa = alertas.listar(db, cenario["de_alfa"])
    do_beta = alertas.listar(db, cenario["de_beta"])

    assert [a.entidade_id for a in do_alfa] == [pt.id]
    assert do_beta == []


def test_auditor_enxerga_as_duas_unidades(
    db: Session, cenario: dict, criar_usuario: Callable[..., Usuario]
) -> None:
    auditor = criar_usuario(matricula="70004", perfil=PerfilUsuario.AUDITOR)
    pt_alfa = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO, unidade="alfa")
    pt_beta = criar_pt(
        db, cenario, estado=EstadoPT.EM_EXECUCAO, unidade="beta", numero="PT-2026-0002"
    )
    alertas.sincronizar(db, pt_alfa.valida_ate + timedelta(hours=1))

    assert {a.entidade_id for a in alertas.listar(db, auditor)} == {pt_alfa.id, pt_beta.id}


# --- indicadores ----------------------------------------------------------------------------


def test_indicadores_contam_no_escopo(db: Session, cenario: dict) -> None:
    criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO, unidade="alfa", numero="PT-2026-0001")
    criar_pt(db, cenario, estado=EstadoPT.RASCUNHO, unidade="alfa", numero="PT-2026-0002")
    criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO, unidade="beta", numero="PT-2026-0003")

    do_alfa = indicadores.calcular(db, cenario["de_alfa"])
    do_beta = indicadores.calcular(db, cenario["de_beta"])

    assert do_alfa.total_de_pts == 2
    assert do_alfa.em_execucao == 1
    assert do_alfa.pts_por_estado == {"EM_EXECUCAO": 1, "RASCUNHO": 1}
    assert do_beta.total_de_pts == 1


def test_janela_fechando_e_vencida_sao_contagens_separadas(
    db: Session, cenario: dict
) -> None:
    """Uma janela que já fechou com gente trabalhando some no meio de uma contagem só."""
    agora = agora_utc()
    criar_pt(
        db, cenario, estado=EstadoPT.EM_EXECUCAO, numero="PT-2026-0001",
        valida_de=agora - timedelta(hours=10), valida_ate=agora - timedelta(hours=1),
    )
    criar_pt(
        db, cenario, estado=EstadoPT.EM_EXECUCAO, numero="PT-2026-0002",
        valida_de=agora - timedelta(hours=1), valida_ate=agora + timedelta(hours=4),
    )

    resultado = indicadores.calcular(db, cenario["de_alfa"])

    assert resultado.vencidas_em_execucao == 1
    assert resultado.janelas_fechando == 1


def test_indicadores_contam_alertas_por_nivel(db: Session, cenario: dict) -> None:
    pt = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO)
    alertas.sincronizar(db, pt.valida_ate + timedelta(hours=HORAS_DE_UM_NIVEL))

    resultado = indicadores.calcular(db, cenario["de_alfa"])

    assert resultado.alertas_abertos == 1
    assert resultado.alertas_por_nivel == {1: 1}


# --- endpoints ------------------------------------------------------------------------------


def test_painel_exige_autenticacao(client: TestClient, db: Session) -> None:
    assert client.get("/indicadores").status_code == 401
    assert client.get("/alertas").status_code == 401


def test_painel_responde_no_escopo(client: TestClient, db: Session, cenario: dict) -> None:
    criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO, unidade="beta")

    resposta = client.get("/indicadores", headers=cenario["cabecalho_alfa"])

    assert resposta.status_code == 200
    assert resposta.json()["total_de_pts"] == 0


def test_o_alerta_traz_o_responsavel_derivado_do_nivel(
    client: TestClient, db: Session, cenario: dict
) -> None:
    pt = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO)
    alertas.sincronizar(db, pt.valida_ate + timedelta(hours=HORAS_DE_UM_NIVEL))

    corpo = client.get("/alertas", headers=cenario["cabecalho_alfa"]).json()

    assert len(corpo) == 1
    assert corpo[0]["nivel_escalonamento"] == 1
    assert corpo[0]["responsavel"] == "coordenador"
    assert corpo[0]["mensagem"].startswith(pt.numero)


def test_sincronizar_e_restrito_a_coordenacao(
    client: TestClient, db: Session, cenario: dict
) -> None:
    """Quem dispara não é quem lê: um alerta que só existe quando alguém clica não é alerta."""
    do_requisitante = client.post(
        "/alertas/sincronizar", headers=cenario["cabecalho_alfa"]
    )
    do_coordenador = client.post(
        "/alertas/sincronizar", headers=cenario["cabecalho_coordenador"]
    )

    assert do_requisitante.status_code == 403
    assert do_coordenador.status_code == 200


def test_filtro_por_nivel_minimo(client: TestClient, db: Session, cenario: dict) -> None:
    pt = criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO)
    alertas.sincronizar(db, pt.valida_ate + timedelta(minutes=1))

    corpo = client.get(
        "/alertas", headers=cenario["cabecalho_alfa"], params={"nivel_minimo": 1}
    ).json()

    assert corpo == []


def test_o_comando_do_agendador_roda_uma_passagem(
    db: Session, cenario: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    """`python -m app.sincronizar_alertas` é a P41: o cron precisa de algo que ele saiba chamar.

    O que este teste guarda é a fiação, não a regra — que já tem os testes acima. Fiação de
    entrypoint quebra em silêncio: o import erra, o comando falha no servidor e o quadro de
    alertas simplesmente para, sem nada na tela dizendo que parou.
    """
    criar_pt(db, cenario, estado=EstadoPT.EM_EXECUCAO, valida_ate=agora_utc() - timedelta(hours=1))

    sincronizar_alertas.main()

    saida = capsys.readouterr().out
    assert "abertos: 1" in saida
    # O carimbo de tempo é metade do valor da linha: log de cron sem ele não diz até quando a
    # sincronização esteve rodando. Confere-se o formato, não o valor — comparar com a data de
    # agora faria o teste cair uma vez a cada muitos anos, na passagem exata da meia-noite, e
    # teste que falha pelo motivo errado é pior que teste nenhum.
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}Z alertas — ", saida)
    assert db.scalars(select(Alerta)).all()
