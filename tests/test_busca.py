"""Busca estruturada, paginação e dossiê."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Area, ModeloPT, PermissaoTrabalho, Unidade, Usuario
from app.models.enums import EstadoPT, PerfilUsuario, TipoTrabalho, TipoUnidade
from app.models.tipos import agora_utc


@pytest.fixture
def cenario(
    client: TestClient, db: Session,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> dict:
    """Duas unidades, dois tipos de trabalho e algumas PTs para filtrar."""
    alfa = Unidade(nome="FPSO Alfa", identificador_operacional="FPSO-A", tipo=TipoUnidade.FPSO)
    beta = Unidade(nome="FPSO Beta", identificador_operacional="FPSO-B", tipo=TipoUnidade.FPSO)
    db.add_all([alfa, beta])
    db.flush()
    area_alfa = Area(unidade_id=alfa.id, nome="Convés", codigo="CV")
    area_beta = Area(unidade_id=beta.id, nome="Convés", codigo="CV")
    quente = ModeloPT(tipo_trabalho=TipoTrabalho.TRABALHO_A_QUENTE, nome="quente", campos=[])
    altura = ModeloPT(tipo_trabalho=TipoTrabalho.TRABALHO_EM_ALTURA, nome="altura", campos=[])
    db.add_all([area_alfa, area_beta, quente, altura])
    db.commit()

    criar_usuario(matricula="70001", unidade_id=alfa.id)
    criar_usuario(matricula="70002", perfil=PerfilUsuario.AUDITOR)
    cabecalho = autenticar("70001")
    inicio = agora_utc()

    descricoes = [
        (quente, TipoTrabalho.TRABALHO_A_QUENTE, "Solda em suporte de tubulação"),
        (quente, TipoTrabalho.TRABALHO_A_QUENTE, "Corte de chapa no convés"),
        (altura, TipoTrabalho.TRABALHO_EM_ALTURA, "Troca de guarda-corpo"),
    ]
    for modelo, tipo, descricao in descricoes:
        client.post(
            "/pts",
            headers=cabecalho,
            json={
                "tipo_trabalho": tipo.value,
                "modelo_pt_id": modelo.id,
                "unidade_id": alfa.id,
                "area_id": area_alfa.id,
                "descricao": descricao,
                "valida_de": inicio.isoformat(),
                "valida_ate": (inicio + timedelta(hours=8)).isoformat(),
            },
        )

    return {"cabecalho": cabecalho, "alfa": alfa, "beta": beta, "area_alfa": area_alfa}


def _buscar(client: TestClient, cenario: dict, **parametros) -> dict:
    return client.get("/pts", headers=cenario["cabecalho"], params=parametros).json()


def test_sem_filtro_devolve_tudo_do_escopo_paginado(client: TestClient, cenario: dict) -> None:
    pagina = _buscar(client, cenario)

    assert pagina["total"] == 3
    assert len(pagina["itens"]) == 3
    assert pagina["limite"] == 50
    assert pagina["deslocamento"] == 0


def test_paginacao_recorta_sem_mentir_no_total(client: TestClient, cenario: dict) -> None:
    """`total` é a contagem antes do recorte — é dele que a tela tira o número de páginas."""
    primeira = _buscar(client, cenario, limite=2)
    segunda = _buscar(client, cenario, limite=2, deslocamento=2)

    assert primeira["total"] == segunda["total"] == 3
    assert len(primeira["itens"]) == 2
    assert len(segunda["itens"]) == 1
    ids = {i["id"] for i in primeira["itens"]} | {i["id"] for i in segunda["itens"]}
    assert len(ids) == 3  # sem sobreposição entre as páginas


@pytest.mark.parametrize(
    ("parametros", "esperado"),
    [
        ({"tipo_trabalho": "trabalho_a_quente"}, 2),
        ({"tipo_trabalho": "trabalho_em_altura"}, 1),
        ({"estado": "RASCUNHO"}, 3),
        ({"estado": "LIBERACAO"}, 0),
        ({"texto": "solda"}, 1),
        ({"texto": "SOLDA"}, 1),
        ({"texto": "convés"}, 1),
        ({"numero": "PT-"}, 3),
        ({"tipo_trabalho": "trabalho_a_quente", "texto": "corte"}, 1),
    ],
)
def test_filtros_combinam_com_e(
    client: TestClient, cenario: dict, parametros: dict, esperado: int
) -> None:
    """Busca textual insensível a maiúsculas: o SQLite só o é em ASCII, e a descrição é PT-BR."""
    assert _buscar(client, cenario, **parametros)["total"] == esperado


def test_filtro_por_unidade_nao_fura_o_escopo(
    client: TestClient, cenario: dict, autenticar: Callable[[str], dict[str, str]]
) -> None:
    """Pedir uma unidade fora do alcance devolve vazio, não a unidade pedida."""
    pagina = _buscar(client, cenario, unidade_id=cenario["beta"].id)

    assert pagina["total"] == 0

    auditor = client.get(
        "/pts", headers=autenticar("70002"), params={"unidade_id": cenario["alfa"].id}
    ).json()
    assert auditor["total"] == 3  # alcance global enxerga a mesma unidade


def test_limite_fora_da_faixa_e_recusado(client: TestClient, cenario: dict) -> None:
    for limite in (0, 500):
        resposta = client.get(
            "/pts", headers=cenario["cabecalho"], params={"limite": limite}
        )
        assert resposta.status_code == 422


def test_dossie_reune_tudo_e_diz_se_a_trilha_esta_integra(
    client: TestClient, cenario: dict, db: Session
) -> None:
    pt_id = _buscar(client, cenario)["itens"][0]["id"]
    client.post(
        f"/pts/{pt_id}/transicoes", headers=cenario["cabecalho"], json={"destino": "VALIDACAO"}
    )

    corpo = client.get(f"/pts/{pt_id}/dossie", headers=cenario["cabecalho"]).json()

    assert corpo["pt"]["id"] == pt_id
    assert corpo["trilha_integra"] is True
    assert corpo["quebras"] == []
    assert len(corpo["versoes"]) == 1  # a versão nasce ao sair do rascunho
    assert corpo["versoes"][0]["versao"] == 1
    assert corpo["versoes"][0]["snapshot"]["numero"] == corpo["pt"]["numero"]
    assert [a["papel"] for a in corpo["assinaturas"]] == ["requisitante"]
    assert [e["tipo_evento"] for e in corpo["eventos"]] == [
        "pt.criada",
        "pt.transicao.validacao",
    ]
    # O dossiê também traz o veredito atual do motor, não só o passado.
    assert any(p["codigo"] == "documento_ausente" for p in corpo["pendencias"])


def test_dossie_denuncia_trilha_adulterada(
    client: TestClient, cenario: dict, db: Session
) -> None:
    """É por isso que a integridade viaja junto: o dossiê é pedido como prova."""
    from sqlalchemy import text

    pt_id = _buscar(client, cenario)["itens"][0]["id"]
    db.execute(
        text("UPDATE audit_event SET motivo = 'reescrito' WHERE pt_id = :i"), {"i": pt_id}
    )
    db.commit()

    corpo = client.get(f"/pts/{pt_id}/dossie", headers=cenario["cabecalho"]).json()

    assert corpo["trilha_integra"] is False
    assert corpo["quebras"]


def test_versoes_e_dossie_respeitam_o_escopo(
    client: TestClient, cenario: dict,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> None:
    pt_id = _buscar(client, cenario)["itens"][0]["id"]
    criar_usuario(matricula="70009", unidade_id=None)
    de_fora = autenticar("70009")

    assert client.get(f"/pts/{pt_id}/dossie", headers=de_fora).status_code == 404
    assert client.get(f"/pts/{pt_id}/versoes", headers=de_fora).status_code == 404


def test_versoes_mostram_o_diff_entre_revisoes(
    client: TestClient, cenario: dict, db: Session,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> None:
    criar_usuario(
        matricula="70003", perfil=PerfilUsuario.AREA_RESPONSAVEL,
        unidade_id=cenario["alfa"].id,
    )
    pt_id = _buscar(client, cenario)["itens"][0]["id"]
    dono = cenario["cabecalho"]

    client.post(f"/pts/{pt_id}/transicoes", headers=dono, json={"destino": "VALIDACAO"})
    client.post(
        f"/pts/{pt_id}/transicoes",
        headers=autenticar("70003"),
        json={"destino": "REJEITADA", "motivo": "Descrição vaga"},
    )
    client.post(f"/pts/{pt_id}/transicoes", headers=dono, json={"destino": "RASCUNHO"})

    db.expire_all()
    atual = db.get(PermissaoTrabalho, pt_id)
    client.patch(
        f"/pts/{pt_id}",
        headers=dono,
        json={
            "tipo_trabalho": atual.tipo_trabalho.value,
            "modelo_pt_id": atual.modelo_pt_id,
            "area_id": atual.area_id,
            "descricao": "Solda em suporte de tubulação — escopo detalhado",
            "valida_de": atual.valida_de.isoformat(),
            "valida_ate": atual.valida_ate.isoformat(),
        },
    )
    client.post(f"/pts/{pt_id}/transicoes", headers=dono, json={"destino": "VALIDACAO"})

    versoes = client.get(f"/pts/{pt_id}/versoes", headers=dono).json()

    assert [v["versao"] for v in versoes] == [1, 2]
    assert versoes[0]["diff"] == {}  # a primeira não tem de quem diferir
    diff = versoes[1]["diff"]
    assert "descricao" in diff
    assert diff["descricao"]["para"].endswith("escopo detalhado")

    db.expire_all()  # quem mudou o estado foi a sessão da requisição, não esta
    assert db.get(PermissaoTrabalho, pt_id).estado == EstadoPT.VALIDACAO
