"""Motor de regras: as decisões de risco, provadas uma a uma.

A maior parte roda sem banco — as regras recebem objetos e devolvem pendências, e é isso que
permite testar cada limite isoladamente em vez de montar meio sistema para cada caso.
"""

from datetime import date, datetime, timedelta

import pytest

from app.models.enums import (
    PapelAssinatura,
    PerfilUsuario,
    TipoAnexo,
    TipoCertificacao,
    TipoTrabalho,
)
from app.models.permissao import Anexo, PermissaoTrabalho, PTEquipe
from app.models.pessoa import Certificacao, Usuario
from app.rules.motor import (
    avaliar_pt,
    certificacoes_da_equipe,
    documentos_obrigatorios,
    janela_de_validade,
    trabalhos_simultaneos,
    validar_assinatura,
)
from app.rules.pendencias import Severidade, bloqueiam

AGORA = datetime(2026, 8, 7, 8, 0)


def _pt(
    tipo: TipoTrabalho = TipoTrabalho.TRABALHO_EM_ALTURA,
    horas: float = 8,
    inicio: datetime = AGORA,
    respostas: dict | None = None,
    pt_id: int = 1,
) -> PermissaoTrabalho:
    return PermissaoTrabalho(
        id=pt_id,
        numero=f"PT-2026-{pt_id:04d}",
        tipo_trabalho=tipo,
        area_id=1,
        requisitante_id=10,
        valida_de=inicio,
        valida_ate=inicio + timedelta(hours=horas),
        respostas=respostas or {},
    )


def _executante(nome: str, tipo: TipoCertificacao | None, vence_em: date | None) -> PTEquipe:
    usuario = Usuario(id=99, nome=nome, perfil=PerfilUsuario.EXECUTANTE)
    if tipo is not None and vence_em is not None:
        usuario.certificacoes = [
            Certificacao(
                tipo=tipo, numero="X", emitida_em=date(2020, 1, 1), valida_ate=vence_em
            )
        ]
    return PTEquipe(usuario=usuario, funcao="Executante")


def _codigos(pendencias) -> set[str]:  # noqa: ANN001
    return {p.codigo for p in pendencias}


# --- janela de validade -------------------------------------------------------------------


def test_janela_dentro_do_limite_nao_gera_pendencia() -> None:
    assert janela_de_validade(_pt(horas=8), AGORA) == []


def test_janela_ja_encerrada_e_bloqueante() -> None:
    vencida = _pt(inicio=AGORA - timedelta(hours=20), horas=8)
    assert "janela_vencida" in _codigos(janela_de_validade(vencida, AGORA))


def test_janela_maior_que_o_maximo_do_tipo_e_bloqueante() -> None:
    """Altura tem teto de 8 h; a quente, 12 h. A mesma janela de 10 h decide diferente."""
    dez_horas_em_altura = _pt(TipoTrabalho.TRABALHO_EM_ALTURA, horas=10)
    dez_horas_a_quente = _pt(TipoTrabalho.TRABALHO_A_QUENTE, horas=10)

    assert "janela_excede_o_maximo" in _codigos(janela_de_validade(dez_horas_em_altura, AGORA))
    assert janela_de_validade(dez_horas_a_quente, AGORA) == []


def test_duracao_declarada_maior_que_a_janela_e_bloqueante() -> None:
    apertada = _pt(horas=4, respostas={"duracao_horas": 6})
    folgada = _pt(horas=8, respostas={"duracao_horas": 6})

    assert "janela_menor_que_a_duracao" in _codigos(janela_de_validade(apertada, AGORA))
    assert janela_de_validade(folgada, AGORA) == []


# --- certificações ------------------------------------------------------------------------


def test_certificacao_precisa_cobrir_o_fim_da_janela_nao_apenas_hoje() -> None:
    """Certificado que vence no meio do serviço deixa o trabalhador sem habilitação exposto."""
    pt = _pt(TipoTrabalho.TRABALHO_EM_ALTURA, horas=8)
    fim = pt.valida_ate.date()

    pt.equipe = [_executante("Rafael", TipoCertificacao.NR_35, fim - timedelta(days=1))]
    assert "certificacao_vencida" in _codigos(certificacoes_da_equipe(pt))

    pt.equipe = [_executante("Rafael", TipoCertificacao.NR_35, fim + timedelta(days=365))]
    assert certificacoes_da_equipe(pt) == []


def test_certificacao_proxima_do_vencimento_avisa_sem_bloquear() -> None:
    pt = _pt(TipoTrabalho.TRABALHO_EM_ALTURA)
    pt.equipe = [
        _executante("Rafael", TipoCertificacao.NR_35, pt.valida_ate.date() + timedelta(days=10))
    ]

    pendencias = certificacoes_da_equipe(pt)

    assert _codigos(pendencias) == {"certificacao_a_vencer"}
    assert bloqueiam(pendencias) == []


def test_certificacao_de_outro_tipo_nao_serve() -> None:
    pt = _pt(TipoTrabalho.ESPACO_CONFINADO)
    pt.equipe = [_executante("Rafael", TipoCertificacao.NR_35, date(2030, 1, 1))]

    assert "certificacao_ausente" in _codigos(certificacoes_da_equipe(pt))


def test_pt_sem_equipe_e_bloqueada_quando_o_tipo_exige_habilitacao() -> None:
    assert "equipe_vazia" in _codigos(certificacoes_da_equipe(_pt(TipoTrabalho.ESPACO_CONFINADO)))


def test_tipo_sem_habilitacao_exigida_nao_cobra_certificacao() -> None:
    """Ausência na tabela significa 'nada a exigir', e não 'esqueci de cadastrar'."""
    assert certificacoes_da_equipe(_pt(TipoTrabalho.ICAMENTO)) == []


# --- documentos ---------------------------------------------------------------------------


def test_documento_exigido_ausente_ou_vencido_bloqueia() -> None:
    pt = _pt(TipoTrabalho.TRABALHO_EM_ALTURA)
    assert _codigos(documentos_obrigatorios(pt)) == {"documento_ausente"}  # exige APR e ASO

    pt.anexos = [
        Anexo(tipo=TipoAnexo.APR, nome_arquivo="apr.pdf", caminho="x", hash_sha256="y"),
        Anexo(
            tipo=TipoAnexo.ASO, nome_arquivo="aso.pdf", caminho="x", hash_sha256="y",
            valido_ate=pt.valida_ate.date() - timedelta(days=1),
        ),
    ]
    assert _codigos(documentos_obrigatorios(pt)) == {"documento_vencido"}

    pt.anexos[1].valido_ate = pt.valida_ate.date() + timedelta(days=30)
    assert documentos_obrigatorios(pt) == []


# --- simultaneidade -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outro_tipo", "bloqueia"),
    [
        (TipoTrabalho.ESPACO_CONFINADO, True),
        (TipoTrabalho.TRABALHO_EM_ALTURA, True),
        (TipoTrabalho.INTERVENCAO_ELETRICA, False),
    ],
)
def test_trabalhos_incompativeis_na_mesma_area(outro_tipo: TipoTrabalho, bloqueia: bool) -> None:
    a_quente = _pt(TipoTrabalho.TRABALHO_A_QUENTE, pt_id=1)
    vizinha = _pt(outro_tipo, pt_id=2)

    pendencias = trabalhos_simultaneos(a_quente, [vizinha])

    assert bool(pendencias) is bloqueia


def test_a_propria_pt_nao_conflita_consigo_mesma() -> None:
    pt = _pt(TipoTrabalho.TRABALHO_A_QUENTE, pt_id=7)
    assert trabalhos_simultaneos(pt, [pt]) == []


# --- segregação de funções ----------------------------------------------------------------


def test_quem_emite_nao_aprova_a_propria_pt() -> None:
    """Regra 8, validada no motor e não na interface."""
    pt = _pt()
    emissor = Usuario(id=10, nome="Carlos", perfil=PerfilUsuario.COORDENADOR, ativo=True)

    como_coordenador = validar_assinatura(pt, emissor, PapelAssinatura.COORDENADOR)

    assert "segregacao_de_funcoes" in _codigos(como_coordenador)


def test_papel_exige_o_perfil_correspondente_inclusive_para_admin() -> None:
    """`admin` administra o sistema; não responde tecnicamente pelo documento."""
    pt = _pt()
    administrador = Usuario(id=42, nome="Root", perfil=PerfilUsuario.ADMIN, ativo=True)

    pendencias = validar_assinatura(pt, administrador, PapelAssinatura.TECNICO_SEGURANCA)

    assert "papel_incompativel_com_o_perfil" in _codigos(pendencias)


def test_assinatura_valida_de_terceiro_com_o_perfil_certo_passa() -> None:
    pt = _pt()
    tecnico = Usuario(
        id=11, nome="Juliana", perfil=PerfilUsuario.TECNICO_SEGURANCA, ativo=True
    )

    assert validar_assinatura(pt, tecnico, PapelAssinatura.TECNICO_SEGURANCA) == []


def test_assinante_inativo_e_recusado() -> None:
    pt = _pt()
    demitido = Usuario(
        id=11, nome="Juliana", perfil=PerfilUsuario.TECNICO_SEGURANCA, ativo=False
    )

    assert "assinante_inativo" in _codigos(
        validar_assinatura(pt, demitido, PapelAssinatura.TECNICO_SEGURANCA)
    )


# --- agregação ----------------------------------------------------------------------------


def test_avaliar_pt_junta_tudo_e_separa_bloqueio_de_aviso() -> None:
    pt = _pt(TipoTrabalho.TRABALHO_EM_ALTURA, horas=10)  # excede o teto de 8 h
    pt.equipe = [
        _executante("Rafael", TipoCertificacao.NR_35, pt.valida_ate.date() + timedelta(days=10))
    ]

    pendencias = avaliar_pt(pt, [], AGORA)
    codigos = _codigos(pendencias)

    assert {"janela_excede_o_maximo", "certificacao_a_vencer", "documento_ausente"} <= codigos
    assert {p.codigo for p in bloqueiam(pendencias)} == {
        "janela_excede_o_maximo",
        "documento_ausente",
    }
    assert all(p.responsavel is not None for p in pendencias)
    assert any(p.severidade == Severidade.ATENCAO for p in pendencias)
