"""Proposta de rascunho: o que a IA escreve, o que ela não escreve, e por onde a PT nasce.

Como no L9, nenhum teste sai para a rede — o agente recebe um cliente falso roteirizado.
"""

import json
from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import rascunho
from app.models import AuditEvent, ModeloPT, PermissaoTrabalho, Usuario
from app.models.enums import EstadoPT, TipoTrabalho
from app.models.tipos import agora_utc
from tests.test_ia import ClienteFalso, texto, turno, uso_de_ferramenta

PROPOSTA = {
    "tipo_trabalho": "trabalho_a_quente",
    "descricao": "Solda de reforço em suporte de tubulação no convés principal",
    "perigos": [
        {"descricao": "Projeção de fagulhas sobre o convés inferior"},
        {"descricao": "Presença de gases inflamáveis na área adjacente"},
    ],
    "controles": [
        {"descricao": "Isolamento da área com manta ignífuga"},
        {"descricao": "Vigia de fogo presente durante todo o serviço e 30 min após"},
    ],
    "justificativa": "Baseado na PT-2026-0001, mesmo tipo de serviço no mesmo convés.",
}


def proposta(**mudancas) -> str:
    return json.dumps(PROPOSTA | mudancas, ensure_ascii=False)


@pytest.fixture
def cenario(
    client: TestClient, db: Session,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> dict:
    """Uma unidade com área e os dois modelos de formulário, e um requisitante lotado nela."""
    from app.models import Area, Unidade
    from app.models.enums import TipoUnidade

    unidade = Unidade(
        nome="FPSO Alfa", identificador_operacional="FPSO-A", tipo=TipoUnidade.FPSO
    )
    db.add(unidade)
    db.flush()
    area = Area(unidade_id=unidade.id, nome="Convés", codigo="CV")
    quente = ModeloPT(
        tipo_trabalho=TipoTrabalho.TRABALHO_A_QUENTE,
        nome="quente",
        campos=[
            {"chave": "teste_de_gases_lie", "rotulo": "Teste de gases (% LIE)",
             "tipo": "numero", "obrigatorio": True},
            {"chave": "vigia_de_fogo", "rotulo": "Vigia de fogo designado",
             "tipo": "texto", "obrigatorio": True},
        ],
    )
    altura = ModeloPT(
        tipo_trabalho=TipoTrabalho.TRABALHO_EM_ALTURA, nome="altura", campos=[]
    )
    db.add_all([area, quente, altura])
    db.commit()

    usuario = criar_usuario(matricula="70001", unidade_id=unidade.id)
    inicio = agora_utc()

    return {
        "cabecalho": autenticar("70001"),
        "usuario": usuario,
        "unidade": unidade,
        "area": area,
        "quente": quente,
        "pedido": {
            "descricao_livre": "preciso soldar um suporte de tubulação no convés principal",
            "unidade_id": unidade.id,
            "area_id": area.id,
            "equipamento_id": None,
            "valida_de": inicio,
            "valida_ate": inicio + timedelta(hours=8),
            # Medições levantadas a bordo, não redigidas: entram pelo pedido.
            "respostas": {"teste_de_gases_lie": 0.8, "vigia_de_fogo": "Carlos Nunes"},
        },
    }


def _propor(db: Session, cenario: dict, cliente: ClienteFalso) -> rascunho.Rascunho:
    return rascunho.propor(db, cenario["usuario"], cenario["pedido"], cliente)


# --- regra 2: nenhum número de segurança sai do modelo ------------------------------------


def test_as_medicoes_passam_intactas_e_o_modelo_nunca_as_ve(
    db: Session, cenario: dict
) -> None:
    """A trave central do loop: medição é levantada a bordo, não redigida.

    `teste_de_gases_lie` sai de um detector calibrado. Chega pelo pedido, é gravada como veio,
    e não entra no que o modelo lê — ele não tem como confirmar nem contradizer uma leitura.
    """
    cliente = ClienteFalso(turno(texto(proposta())))

    resultado = _propor(db, cenario, cliente)

    assert resultado.pt.respostas == cenario["pedido"]["respostas"]
    enviado = json.dumps(cliente.chamadas[0], default=str)
    assert "0.8" not in enviado
    assert "Carlos Nunes" not in enviado


def test_o_esquema_nao_tem_campo_para_respostas(db: Session) -> None:
    """Tripwire: não existe caminho pelo qual o modelo devolva resposta de formulário.

    `additionalProperties: false` recusa qualquer chave fora desta lista, então a garantia é
    do schema, não da boa vontade do modelo.
    """
    propriedades = rascunho.ESQUEMA["schema"]["properties"]

    assert set(propriedades) == {
        "tipo_trabalho", "descricao", "perigos", "controles", "justificativa"
    }
    assert rascunho.ESQUEMA["schema"]["additionalProperties"] is False


def test_a_janela_vem_do_pedido_e_nao_do_modelo(db: Session, cenario: dict) -> None:
    resultado = _propor(db, cenario, ClienteFalso(turno(texto(proposta()))))

    assert resultado.pt.valida_de == cenario["pedido"]["valida_de"]
    assert resultado.pt.valida_ate == cenario["pedido"]["valida_ate"]


def test_a_requisicao_prende_a_saida_ao_esquema(db: Session, cenario: dict) -> None:
    cliente = ClienteFalso(turno(texto(proposta())))

    _propor(db, cenario, cliente)

    assert cliente.chamadas[0]["output_config"]["format"] == rascunho.ESQUEMA


# --- regra 1: propor não é aprovar --------------------------------------------------------


def test_a_pt_nasce_em_rascunho_e_pelo_caminho_normal(db: Session, cenario: dict) -> None:
    resultado = _propor(db, cenario, ClienteFalso(turno(texto(proposta()))))
    db.expire_all()

    pt = db.scalars(select(PermissaoTrabalho)).one()
    assert pt.estado == EstadoPT.RASCUNHO
    assert pt.versao == 1
    assert pt.numero.startswith(f"PT-{agora_utc().year}-")
    # Requisitante é o usuário autenticado, nunca o modelo.
    assert pt.requisitante_id == cenario["usuario"].id
    assert resultado.pt.id == pt.id


def test_a_trilha_marca_a_origem_do_rascunho(db: Session, cenario: dict) -> None:
    """Um rascunho proposto pela IA fica distinguível para sempre, sem mudar o payload."""
    _propor(db, cenario, ClienteFalso(turno(texto(proposta()))))
    db.expire_all()

    evento = db.scalars(select(AuditEvent)).one()
    assert evento.tipo_evento == "pt.criada_por_ia"
    assert evento.estado_destino == EstadoPT.RASCUNHO
    assert evento.ator_id == cenario["usuario"].id


def test_as_pendencias_saem_do_motor_de_regras(db: Session, cenario: dict) -> None:
    """O que falta é o veredito do L4 — o mesmo que barra a liberação depois."""
    resultado = _propor(db, cenario, ClienteFalso(turno(texto(proposta()))))

    codigos = {p.codigo for p in resultado.pendencias}
    # Rascunho recém-nascido não tem equipe nem documento anexado.
    assert "equipe_vazia" in codigos


def test_formulario_incompleto_para_o_tipo_escolhido_responde_409(
    db: Session, cenario: dict
) -> None:
    """A IA escolhe o tipo, então as respostas enviadas podem não servir para ele.

    Não é caso especial: é a mesma recusa que uma PT criada à mão receberia, com a lista dos
    campos que faltam — e nenhuma PT fica no banco.
    """
    from app.rules.pendencias import ConflitoDeNegocio

    faltando = cenario["pedido"] | {"respostas": {"vigia_de_fogo": "Carlos Nunes"}}

    with pytest.raises(ConflitoDeNegocio) as erro:
        rascunho.propor(
            db, cenario["usuario"], faltando, ClienteFalso(turno(texto(proposta())))
        )

    assert [p.campo for p in erro.value.pendencias] == ["teste_de_gases_lie"]
    db.expire_all()
    assert db.scalars(select(PermissaoTrabalho)).all() == []


# --- proposta inválida --------------------------------------------------------------------


def test_tipo_de_trabalho_inexistente_e_recusado(db: Session, cenario: dict) -> None:
    cliente = ClienteFalso(turno(texto(proposta(tipo_trabalho="mergulho_saturado"))))

    with pytest.raises(rascunho.PropostaInvalida):
        _propor(db, cenario, cliente)
    db.expire_all()
    assert db.scalars(select(PermissaoTrabalho)).all() == []


def test_json_quebrado_nao_cria_pt(db: Session, cenario: dict) -> None:
    cliente = ClienteFalso(turno(texto("desculpe, não consegui")))

    with pytest.raises(rascunho.PropostaInvalida):
        _propor(db, cenario, cliente)
    db.expire_all()
    assert db.scalars(select(PermissaoTrabalho)).all() == []


def test_tipo_sem_modelo_ativo_e_recusado(db: Session, cenario: dict) -> None:
    """Sem formulário aprovado para o tipo não há PT — e o erro diz qual tipo faltou."""
    cliente = ClienteFalso(turno(texto(proposta(tipo_trabalho="icamento"))))

    with pytest.raises(rascunho.PropostaInvalida, match="icamento"):
        _propor(db, cenario, cliente)


def test_recusa_do_modelo_nao_cria_pt(db: Session, cenario: dict) -> None:
    with pytest.raises(rascunho.PropostaInvalida, match="recusou"):
        _propor(db, cenario, ClienteFalso(turno(parada="refusal")))
    db.expire_all()
    assert db.scalars(select(PermissaoTrabalho)).all() == []


# --- ferramentas no meio do caminho -------------------------------------------------------


def test_consulta_pts_parecidas_antes_de_propor(db: Session, cenario: dict) -> None:
    """As mesmas ferramentas somente-leitura do L9, com o escopo já aplicado."""
    cliente = ClienteFalso(
        turno(uso_de_ferramenta("buscar_pts", {"tipo_trabalho": "trabalho_a_quente"}),
              parada="tool_use"),
        turno(texto(proposta())),
    )

    resultado = _propor(db, cenario, cliente)

    assert len(cliente.chamadas) == 2
    # Banco sem PT anterior: nada a citar, e a proposta sai mesmo assim.
    assert resultado.fontes == []
    assert resultado.justificativa


# --- endpoint -----------------------------------------------------------------------------


def test_rascunho_exige_autenticacao(client: TestClient, db: Session) -> None:
    resposta = client.post("/ai/rascunho", json={"descricao_livre": "soldar um suporte"})

    assert resposta.status_code == 401


def test_rascunho_sem_chave_responde_503(client: TestClient, cenario: dict) -> None:
    pedido = cenario["pedido"] | {
        "valida_de": cenario["pedido"]["valida_de"].isoformat(),
        "valida_ate": cenario["pedido"]["valida_ate"].isoformat(),
    }

    resposta = client.post("/ai/rascunho", headers=cenario["cabecalho"], json=pedido)

    assert resposta.status_code == 503
    assert "chave" in resposta.json()["detail"]


def test_janela_invertida_e_rejeitada(client: TestClient, cenario: dict) -> None:
    inicio = cenario["pedido"]["valida_de"]
    pedido = cenario["pedido"] | {
        "valida_de": inicio.isoformat(),
        "valida_ate": (inicio - timedelta(hours=1)).isoformat(),
    }

    resposta = client.post("/ai/rascunho", headers=cenario["cabecalho"], json=pedido)

    assert resposta.status_code == 422
