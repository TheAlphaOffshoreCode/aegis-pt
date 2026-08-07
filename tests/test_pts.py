"""CRUD de PT: numeração, formulário dinâmico, escopo e limites de edição."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Area, Equipamento, ModeloPT, Unidade, Usuario
from app.models.enums import (
    Criticidade,
    EstadoPT,
    PerfilUsuario,
    TipoTrabalho,
    TipoUnidade,
)
from app.models.permissao import PermissaoTrabalho
from app.models.tipos import agora_utc

CAMPOS = [
    {"chave": "altura_metros", "rotulo": "Altura (m)", "tipo": "numero", "obrigatorio": True},
    {"chave": "ancoragem", "rotulo": "Ancoragem", "tipo": "selecao", "obrigatorio": True,
     "opcoes": ["linha_de_vida", "ponto_fixo"]},
]
RESPOSTAS = {"altura_metros": 8.0, "ancoragem": "ponto_fixo"}


@pytest.fixture
def cenario(db: Session) -> dict:
    """Duas unidades, para que o escopo tenha o que separar."""
    alfa = Unidade(nome="FPSO Alfa", identificador_operacional="FPSO-A", tipo=TipoUnidade.FPSO)
    beta = Unidade(nome="FPSO Beta", identificador_operacional="FPSO-B", tipo=TipoUnidade.FPSO)
    db.add_all([alfa, beta])
    db.flush()

    area_alfa = Area(unidade_id=alfa.id, nome="Convés", codigo="CV")
    area_beta = Area(unidade_id=beta.id, nome="Convés", codigo="CV")
    db.add_all([area_alfa, area_beta])
    db.flush()

    equipamento = Equipamento(
        area_id=area_alfa.id, tag="B-1", descricao="Bomba", criticidade=Criticidade.ALTA
    )
    equipamento_beta = Equipamento(
        area_id=area_beta.id, tag="B-2", descricao="Bomba", criticidade=Criticidade.ALTA
    )
    altura = ModeloPT(
        tipo_trabalho=TipoTrabalho.TRABALHO_EM_ALTURA, nome="PT altura", campos=CAMPOS
    )
    quente = ModeloPT(
        tipo_trabalho=TipoTrabalho.TRABALHO_A_QUENTE, nome="PT quente", campos=[]
    )
    db.add_all([equipamento, equipamento_beta, altura, quente])
    db.commit()

    return {
        "alfa": alfa, "beta": beta, "area_alfa": area_alfa, "area_beta": area_beta,
        "equipamento": equipamento, "equipamento_beta": equipamento_beta,
        "modelo_altura": altura, "modelo_quente": quente,
    }


def _payload(cenario: dict, **ajustes) -> dict:
    inicio = agora_utc()
    base = {
        "tipo_trabalho": TipoTrabalho.TRABALHO_EM_ALTURA.value,
        "modelo_pt_id": cenario["modelo_altura"].id,
        "unidade_id": cenario["alfa"].id,
        "area_id": cenario["area_alfa"].id,
        "descricao": "Troca de guarda-corpo do convés principal",
        "valida_de": inicio.isoformat(),
        "valida_ate": (inicio + timedelta(hours=8)).isoformat(),
        "respostas": dict(RESPOSTAS),
    }
    return base | ajustes


def _codigos(resposta) -> set[str]:  # noqa: ANN001
    return {item["codigo"] for item in resposta.json()["detail"]}


def test_pt_nasce_em_rascunho_com_numero_do_servidor(
    client: TestClient, cenario: dict,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Número, estado e requisitante são do servidor — o que o cliente mandar é ignorado."""
    criar_usuario(matricula="70001", unidade_id=cenario["alfa"].id)
    outro = criar_usuario(matricula="70002", unidade_id=cenario["alfa"].id)
    cabecalho = autenticar("70001")

    corpo = client.post(
        "/pts",
        json=_payload(cenario, estado="LIBERACAO", numero="PT-FALSA", requisitante_id=outro.id),
        headers=cabecalho,
    ).json()

    ano = agora_utc().year
    assert corpo["numero"] == f"PT-{ano}-0001"
    assert corpo["estado"] == EstadoPT.RASCUNHO
    assert corpo["versao"] == 1
    assert corpo["requisitante_id"] != outro.id

    segunda = client.post("/pts", json=_payload(cenario), headers=cabecalho).json()
    assert segunda["numero"] == f"PT-{ano}-0002"


@pytest.mark.parametrize(
    ("ajuste", "codigo"),
    [
        ({"respostas": {"ancoragem": "ponto_fixo"}}, "campo_obrigatorio"),
        ({"respostas": {**RESPOSTAS, "ancoragem": "corda"}}, "opcao_invalida"),
        ({"respostas": {**RESPOSTAS, "extra": 1}}, "campo_desconhecido"),
        ({"respostas": {**RESPOSTAS, "altura_metros": True}}, "tipo_invalido"),
    ],
)
def test_formulario_invalido_responde_409_com_pendencia_estruturada(
    client: TestClient, cenario: dict, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]], ajuste: dict, codigo: str,
) -> None:
    criar_usuario(matricula="70001", unidade_id=cenario["alfa"].id)

    resposta = client.post(
        "/pts", json=_payload(cenario, **ajuste), headers=autenticar("70001")
    )

    assert resposta.status_code == 409
    assert codigo in _codigos(resposta)
    assert all(item["severidade"] == "bloqueante" for item in resposta.json()["detail"])


def test_estrutura_incoerente_e_recusada(
    client: TestClient, cenario: dict, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Área de outra unidade, equipamento de outra área, modelo de outro tipo."""
    criar_usuario(matricula="70001", perfil=PerfilUsuario.ADMIN)
    cabecalho = autenticar("70001")

    combinacoes = [
        ({"area_id": cenario["area_beta"].id}, "area_invalida"),
        ({"equipamento_id": cenario["equipamento_beta"].id}, "equipamento_invalido"),
        ({"modelo_pt_id": cenario["modelo_quente"].id}, "modelo_incompativel"),
    ]
    for ajuste, codigo in combinacoes:
        resposta = client.post("/pts", json=_payload(cenario, **ajuste), headers=cabecalho)
        assert resposta.status_code == 409
        assert codigo in _codigos(resposta)


def test_escopo_esconde_pt_de_outra_unidade_e_auditor_ve_tudo(
    client: TestClient, cenario: dict, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Fora do escopo responde 404: 403 já confirmaria que a PT existe."""
    criar_usuario(matricula="70001", unidade_id=cenario["alfa"].id)
    criar_usuario(matricula="70002", unidade_id=cenario["beta"].id)
    criar_usuario(matricula="70003", perfil=PerfilUsuario.AUDITOR)

    pt = client.post("/pts", json=_payload(cenario), headers=autenticar("70001")).json()

    de_fora = autenticar("70002")
    assert client.get(f"/pts/{pt['id']}", headers=de_fora).status_code == 404
    pagina = client.get("/pts", headers=de_fora).json()
    # O `total` também é do escopo: contar num universo maior que o exibido já diria
    # quantas PTs existem fora do alcance de quem perguntou.
    assert pagina["itens"] == []
    assert pagina["total"] == 0

    auditor = autenticar("70003")
    assert client.get(f"/pts/{pt['id']}", headers=auditor).status_code == 200
    assert client.get("/pts", headers=auditor).json()["total"] == 1


def test_criar_pt_em_unidade_fora_da_lotacao_e_bloqueado(
    client: TestClient, cenario: dict, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    criar_usuario(matricula="70001", unidade_id=cenario["alfa"].id)

    resposta = client.post(
        "/pts",
        json=_payload(cenario, unidade_id=cenario["beta"].id, area_id=cenario["area_beta"].id),
        headers=autenticar("70001"),
    )

    assert resposta.status_code == 409
    assert "fora_do_escopo" in _codigos(resposta)


def test_executante_nao_emite_pt(
    client: TestClient, cenario: dict, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    criar_usuario(
        matricula="70001", perfil=PerfilUsuario.EXECUTANTE, unidade_id=cenario["alfa"].id
    )

    resposta = client.post("/pts", json=_payload(cenario), headers=autenticar("70001"))

    assert resposta.status_code == 403


def test_rascunho_so_e_corrigido_pelo_requisitante_e_so_enquanto_e_rascunho(
    client: TestClient, db: Session, cenario: dict,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> None:
    criar_usuario(matricula="70001", unidade_id=cenario["alfa"].id)
    criar_usuario(matricula="70002", unidade_id=cenario["alfa"].id)
    dono = autenticar("70001")
    pt = client.post("/pts", json=_payload(cenario), headers=dono).json()

    correcao = _payload(cenario, descricao="Descrição corrigida")
    correcao.pop("unidade_id")  # a unidade não muda: mudá-la seria outra PT

    assert client.patch(f"/pts/{pt['id']}", json=correcao, headers=dono).status_code == 200
    assert client.get(f"/pts/{pt['id']}", headers=dono).json()["descricao"] == "Descrição corrigida"

    de_outro = client.patch(f"/pts/{pt['id']}", json=correcao, headers=autenticar("70002"))
    assert de_outro.status_code == 409
    assert "nao_e_o_requisitante" in _codigos(de_outro)

    db.get(PermissaoTrabalho, pt["id"]).estado = EstadoPT.APROVACAO
    db.commit()
    fora_de_rascunho = client.patch(f"/pts/{pt['id']}", json=correcao, headers=dono)
    assert fora_de_rascunho.status_code == 409
    assert "pt_nao_editavel" in _codigos(fora_de_rascunho)


def test_modelo_do_tipo_entrega_os_campos_do_formulario(
    client: TestClient, cenario: dict, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """A rota `/pts/modelos/...` precisa vir antes de `/pts/{id}`, senão nunca é alcançada."""
    criar_usuario(matricula="70001", unidade_id=cenario["alfa"].id)

    corpo = client.get(
        f"/pts/modelos/{TipoTrabalho.TRABALHO_EM_ALTURA.value}", headers=autenticar("70001")
    ).json()

    assert [campo["chave"] for campo in corpo["campos"]] == ["altura_metros", "ancoragem"]


def test_equipe_com_membro_inexistente_vira_pendencia_e_nao_erro_de_banco(
    client: TestClient, cenario: dict, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Sem a checagem, isto explodiria como violação de chave estrangeira no commit."""
    criar_usuario(matricula="70001", unidade_id=cenario["alfa"].id)
    inativo = criar_usuario(matricula="70002", unidade_id=cenario["alfa"].id, ativo=False)

    for usuario_id in (99999, inativo.id):
        resposta = client.post(
            "/pts",
            json=_payload(cenario, equipe=[{"usuario_id": usuario_id, "funcao": "Soldador"}]),
            headers=autenticar("70001"),
        )
        assert resposta.status_code == 409
        assert "membro_invalido" in _codigos(resposta)


def test_equipe_valida_e_gravada_junto_com_a_pt(
    client: TestClient, db: Session, cenario: dict,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> None:
    criar_usuario(matricula="70001", unidade_id=cenario["alfa"].id)
    executante = criar_usuario(
        matricula="70002", perfil=PerfilUsuario.EXECUTANTE, unidade_id=cenario["alfa"].id
    )

    pt = client.post(
        "/pts",
        json=_payload(cenario, equipe=[{"usuario_id": executante.id, "funcao": "Soldador"}]),
        headers=autenticar("70001"),
    ).json()

    equipe = db.get(PermissaoTrabalho, pt["id"]).equipe
    assert [(m.usuario_id, m.funcao) for m in equipe] == [(executante.id, "Soldador")]


def test_pendencias_reprovam_pt_sem_certificacao_nem_documento(
    client: TestClient, cenario: dict, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """O endpoint é consulta: responde 200 mesmo cheio de pendência bloqueante."""
    criar_usuario(matricula="70001", unidade_id=cenario["alfa"].id)
    executante = criar_usuario(
        matricula="70002", perfil=PerfilUsuario.EXECUTANTE, unidade_id=cenario["alfa"].id
    )
    cabecalho = autenticar("70001")
    pt = client.post(
        "/pts",
        json=_payload(cenario, equipe=[{"usuario_id": executante.id, "funcao": "Montador"}]),
        headers=cabecalho,
    ).json()

    avaliacao = client.get(f"/pts/{pt['id']}/pendencias", headers=cabecalho)

    assert avaliacao.status_code == 200
    corpo = avaliacao.json()
    assert corpo["liberavel"] is False
    codigos = {p["codigo"] for p in corpo["pendencias"]}
    assert "certificacao_ausente" in codigos  # trabalho em altura exige NR-35
    assert "documento_ausente" in codigos  # e APR mais ASO


def test_pendencia_de_simultaneidade_depende_da_sobreposicao_real_da_janela(
    client: TestClient, db: Session, cenario: dict,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> None:
    """A PT vizinha começou antes e ainda não terminou — comparar só os inícios a deixaria passar."""
    criar_usuario(matricula="70001", unidade_id=cenario["alfa"].id)
    cabecalho = autenticar("70001")
    pt = client.post("/pts", json=_payload(cenario), headers=cabecalho).json()
    alvo = db.get(PermissaoTrabalho, pt["id"])

    vizinha = PermissaoTrabalho(
        numero="PT-2026-9999",
        tipo_trabalho=TipoTrabalho.TRABALHO_A_QUENTE,
        estado=EstadoPT.EM_EXECUCAO,
        modelo_pt_id=cenario["modelo_quente"].id,
        unidade_id=cenario["alfa"].id,
        area_id=cenario["area_alfa"].id,
        requisitante_id=alvo.requisitante_id,
        descricao="Solda iniciada antes",
        valida_de=alvo.valida_de - timedelta(hours=2),
        valida_ate=alvo.valida_de + timedelta(hours=1),
    )
    db.add(vizinha)
    db.commit()

    codigos = {
        p["codigo"]
        for p in client.get(f"/pts/{pt['id']}/pendencias", headers=cabecalho).json()["pendencias"]
    }
    assert "trabalhos_incompativeis" in codigos

    # Afastada no tempo, a mesma vizinha deixa de conflitar.
    vizinha.valida_de = alvo.valida_ate + timedelta(hours=1)
    vizinha.valida_ate = alvo.valida_ate + timedelta(hours=5)
    db.commit()

    codigos = {
        p["codigo"]
        for p in client.get(f"/pts/{pt['id']}/pendencias", headers=cabecalho).json()["pendencias"]
    }
    assert "trabalhos_incompativeis" not in codigos


def test_pendencias_de_pt_fora_do_escopo_respondem_404(
    client: TestClient, cenario: dict, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    criar_usuario(matricula="70001", unidade_id=cenario["alfa"].id)
    criar_usuario(matricula="70002", unidade_id=cenario["beta"].id)
    pt = client.post("/pts", json=_payload(cenario), headers=autenticar("70001")).json()

    resposta = client.get(f"/pts/{pt['id']}/pendencias", headers=autenticar("70002"))

    assert resposta.status_code == 404


def test_listar_sem_autenticacao_e_recusado(client: TestClient) -> None:
    assert client.get("/pts").status_code == 401
