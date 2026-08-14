"""Anexos: hash no servidor, nome do cliente como rótulo, e download que não vira página."""

import hashlib
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Anexo, Area, AuditEvent, ModeloPT, PermissaoTrabalho, Unidade, Usuario
from app.models.enums import EstadoPT, PerfilUsuario, TipoTrabalho, TipoUnidade
from app.models.tipos import agora_utc
from tests.conftest import assinatura

CONTEUDO = b"%PDF-1.4 conteudo de teste da analise preliminar de risco"


@pytest.fixture
def cenario(
    client: TestClient, db: Session,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> dict:
    unidade = Unidade(
        nome="FPSO de teste", identificador_operacional="FPSO-T", tipo=TipoUnidade.FPSO
    )
    db.add(unidade)
    db.flush()
    area = Area(unidade_id=unidade.id, nome="Convés", codigo="CV")
    modelo = ModeloPT(tipo_trabalho=TipoTrabalho.TRABALHO_A_QUENTE, nome="PT quente", campos=[])
    db.add_all([area, modelo])
    db.commit()

    criar_usuario(matricula="70001", unidade_id=unidade.id)
    criar_usuario(matricula="70002", unidade_id=unidade.id)
    cabecalho = autenticar("70001")

    inicio = agora_utc()
    pt = client.post(
        "/pts",
        headers=cabecalho,
        json={
            "tipo_trabalho": TipoTrabalho.TRABALHO_A_QUENTE.value,
            "modelo_pt_id": modelo.id,
            "unidade_id": unidade.id,
            "area_id": area.id,
            "descricao": "Solda em suporte",
            "valida_de": inicio.isoformat(),
            "valida_ate": (inicio + timedelta(hours=8)).isoformat(),
        },
    ).json()
    return {"pt_id": pt["id"], "cabecalho": cabecalho, "unidade": unidade}


def _anexar(
    client: TestClient, cenario: dict, *, nome: str = "apr.pdf", conteudo: bytes = CONTEUDO,
    tipo: str = "apr", valido_ate: str | None = None, cabecalho: dict | None = None,
):  # noqa: ANN201
    dados = {"tipo": tipo}
    if valido_ate:
        dados["valido_ate"] = valido_ate
    return client.post(
        f"/pts/{cenario['pt_id']}/anexos",
        headers=cabecalho or cenario["cabecalho"],
        files={"arquivo": (nome, conteudo, "application/pdf")},
        data=dados,
    )


def _codigos(resposta) -> set[str]:  # noqa: ANN001
    return {p["codigo"] for p in resposta.json()["detail"]}


def test_anexo_e_gravado_com_hash_do_servidor_e_nome_gerado(
    client: TestClient, cenario: dict, db: Session
) -> None:
    """O nome enviado é rótulo; o caminho em disco é nosso, e o hash sai do conteúdo real."""
    resposta = _anexar(client, cenario, nome="APR assinada.pdf")

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["nome_arquivo"] == "APR assinada.pdf"
    assert corpo["hash_sha256"] == hashlib.sha256(CONTEUDO).hexdigest()

    anexo = db.scalars(select(Anexo)).one()
    caminho = Path(anexo.caminho)
    assert caminho.exists()
    assert caminho.read_bytes() == CONTEUDO
    assert "APR assinada" not in caminho.name  # nome do cliente não vira caminho
    assert caminho.parent.name == db.get(PermissaoTrabalho, cenario["pt_id"]).uuid


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("../../etc/passwd.pdf", "passwd.pdf"),
        # Barra invertida precisa cair também no Linux, onde `Path` não a trata como
        # separador — foi assim que a primeira versão passou aqui e quebrou no CI.
        ("..\\..\\windows\\system32\\sam.pdf", "sam.pdf"),
        ("sub/dir/apr.pdf", "apr.pdf"),
        ("C:\\Users\\alguem\\aso.pdf", "aso.pdf"),
    ],
)
def test_caminho_no_nome_enviado_vira_apenas_o_nome(
    client: TestClient, cenario: dict, db: Session, nome: str, esperado: str
) -> None:
    """O nome é rótulo, mas rótulo com `../` acaba usado como caminho por alguém, algum dia."""
    resposta = _anexar(client, cenario, nome=nome)

    assert resposta.status_code == 201
    assert db.scalars(select(Anexo)).one().nome_arquivo == esperado


@pytest.mark.parametrize(
    ("nome", "codigo"),
    [
        ("payload.html", "extensao_nao_permitida"),
        ("script.svg", "extensao_nao_permitida"),
        ("binario.exe", "extensao_nao_permitida"),
        ("sem_extensao", "extensao_nao_permitida"),
    ],
)
def test_extensoes_fora_da_allowlist_sao_recusadas(
    client: TestClient, cenario: dict, nome: str, codigo: str
) -> None:
    """`.html` e `.svg` de fora de propósito: o navegador os renderizaria como página."""
    resposta = _anexar(client, cenario, nome=nome)

    assert resposta.status_code == 409
    assert codigo in _codigos(resposta)


def test_arquivo_vazio_e_recusado_e_nao_deixa_rastro_em_disco(
    client: TestClient, cenario: dict, db: Session
) -> None:
    resposta = _anexar(client, cenario, conteudo=b"")

    assert resposta.status_code == 409
    assert "arquivo_vazio" in _codigos(resposta)
    assert db.scalars(select(Anexo)).all() == []
    pasta = get_settings().upload_dir
    assert not any(pasta.rglob("*.pdf"))


def test_arquivo_acima_do_limite_e_recusado_sem_sobrar_arquivo(
    client: TestClient, cenario: dict, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aborta durante a leitura, e o que já foi escrito é apagado.

    O conteúdo precisa ser um PDF de verdade: desde o L13 a conferência de assinatura roda no
    primeiro bloco e recusaria antes, por outro motivo.
    """
    monkeypatch.setenv("AEGIS_ANEXO_TAMANHO_MAXIMO_MB", "0")
    get_settings.cache_clear()
    try:
        resposta = _anexar(client, cenario, conteudo=b"%PDF-1.4" + b"x" * 5000)
    finally:
        monkeypatch.delenv("AEGIS_ANEXO_TAMANHO_MAXIMO_MB", raising=False)
        get_settings.cache_clear()

    assert resposta.status_code == 409
    assert "arquivo_muito_grande" in _codigos(resposta)
    assert db.scalars(select(Anexo)).all() == []
    assert not any(get_settings().upload_dir.rglob("*.pdf"))


def test_download_vem_como_anexo_e_nunca_como_pagina(
    client: TestClient, cenario: dict, db: Session
) -> None:
    anexo_id = _anexar(client, cenario).json()["id"]

    resposta = client.get(
        f"/pts/{cenario['pt_id']}/anexos/{anexo_id}/conteudo", headers=cenario["cabecalho"]
    )

    assert resposta.status_code == 200
    assert resposta.content == CONTEUDO
    assert resposta.headers["content-disposition"].startswith("attachment")
    assert resposta.headers["x-content-type-options"] == "nosniff"
    assert resposta.headers["content-type"] == "application/pdf"


def test_anexo_de_pt_fora_do_escopo_nao_e_alcancavel(
    client: TestClient, cenario: dict,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> None:
    anexo_id = _anexar(client, cenario).json()["id"]
    criar_usuario(matricula="70009", unidade_id=None)  # sem lotação
    de_fora = autenticar("70009")

    assert client.get(f"/pts/{cenario['pt_id']}/anexos", headers=de_fora).status_code == 404
    assert client.get(
        f"/pts/{cenario['pt_id']}/anexos/{anexo_id}/conteudo", headers=de_fora
    ).status_code == 404
    assert _anexar(client, cenario, cabecalho=de_fora).status_code == 404


def test_remover_anexo_do_rascunho_apaga_o_arquivo_e_deixa_rastro(
    client: TestClient, cenario: dict, db: Session
) -> None:
    anexo_id = _anexar(client, cenario).json()["id"]
    caminho = Path(db.scalars(select(Anexo)).one().caminho)
    assert caminho.exists()

    resposta = client.delete(
        f"/pts/{cenario['pt_id']}/anexos/{anexo_id}", headers=cenario["cabecalho"]
    )

    assert resposta.status_code == 204
    db.expire_all()
    assert db.scalars(select(Anexo)).all() == []
    assert not caminho.exists()

    tipos = [
        e.tipo_evento
        for e in db.scalars(
            select(AuditEvent).where(AuditEvent.pt_id == cenario["pt_id"])
        ).all()
    ]
    assert "pt.anexo.adicionado" in tipos
    assert "pt.anexo.removido" in tipos


def test_anexo_nao_sai_depois_que_a_pt_circulou(
    client: TestClient, cenario: dict, db: Session
) -> None:
    """Depois de enviada, o anexo faz parte do que as pessoas analisaram."""
    anexo_id = _anexar(client, cenario).json()["id"]
    assert client.post(
        f"/pts/{cenario['pt_id']}/transicoes",
        headers=cenario["cabecalho"],
        json={"destino": "VALIDACAO", **assinatura("70001")},
    ).status_code == 200

    resposta = client.delete(
        f"/pts/{cenario['pt_id']}/anexos/{anexo_id}", headers=cenario["cabecalho"]
    )

    assert resposta.status_code == 409
    assert "anexo_nao_removivel" in _codigos(resposta)
    assert Path(db.scalars(select(Anexo)).one().caminho).exists()


def test_apenas_o_requisitante_remove_anexo(
    client: TestClient, cenario: dict, autenticar: Callable[[str], dict[str, str]]
) -> None:
    anexo_id = _anexar(client, cenario).json()["id"]

    resposta = client.delete(
        f"/pts/{cenario['pt_id']}/anexos/{anexo_id}", headers=autenticar("70002")
    )

    assert resposta.status_code == 409
    assert "nao_e_o_requisitante" in _codigos(resposta)


def test_anexar_apr_faz_o_motor_parar_de_cobrar_o_documento(
    client: TestClient, cenario: dict
) -> None:
    """Fecha o ciclo com o L4: a pendência que existia desde então some quando o papel chega."""
    antes = client.get(
        f"/pts/{cenario['pt_id']}/pendencias", headers=cenario["cabecalho"]
    ).json()
    assert "documento_ausente" in {p["codigo"] for p in antes["pendencias"]}

    _anexar(client, cenario)

    depois = client.get(
        f"/pts/{cenario['pt_id']}/pendencias", headers=cenario["cabecalho"]
    ).json()
    assert "documento_ausente" not in {p["codigo"] for p in depois["pendencias"]}


def test_apr_vencida_antes_do_fim_da_janela_e_pendencia(
    client: TestClient, cenario: dict
) -> None:
    ontem = (date.today() - timedelta(days=1)).isoformat()

    _anexar(client, cenario, valido_ate=ontem)

    pendencias = client.get(
        f"/pts/{cenario['pt_id']}/pendencias", headers=cenario["cabecalho"]
    ).json()["pendencias"]

    assert "documento_vencido" in {p["codigo"] for p in pendencias}
