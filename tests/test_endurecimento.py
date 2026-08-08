"""L13 — o que o endurecimento fechou, provado.

Cada teste aqui corresponde a uma pendência declarada em algum loop anterior. Auditoria que só
produz texto não fecha nada: o que fecha é o teste que falha se a proteção sair.
"""

from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Area, ModeloPT, PermissaoTrabalho, Unidade, Usuario
from app.models.enums import EstadoPT, PerfilUsuario, TipoTrabalho, TipoUnidade
from app.models.tipos import agora_utc
from app.security import limite
from app.security.arquivos import confere
from app.security.cabecalhos import CABECALHOS


@pytest.fixture(autouse=True)
def _limitadores_zerados() -> None:
    """Os limitadores são estado de processo: um teste não pode herdar o do anterior."""
    limite.LOGIN._marcas.clear()
    limite.IA._marcas.clear()


# --- P3: cabeçalhos de segurança ------------------------------------------------------------


def test_toda_resposta_leva_os_cabecalhos(client: TestClient) -> None:
    resposta = client.get("/health")

    for nome, valor in CABECALHOS.items():
        assert resposta.headers[nome] == valor


def test_os_cabecalhos_saem_tambem_no_erro(client: TestClient) -> None:
    """Resposta de erro é resposta: sem cabeçalho, a proteção some justo onde há falha."""
    resposta = client.get("/pts")

    assert resposta.status_code == 401
    assert resposta.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in resposta.headers["Content-Security-Policy"]


def test_a_csp_nao_abre_excecao_para_inline(client: TestClient) -> None:
    """O PWA é vanilla, sem script inline: não há motivo para `unsafe-inline` existir."""
    csp = client.get("/").headers["Content-Security-Policy"]

    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert "script-src 'self'" in csp


def test_sem_hsts_em_desenvolvimento(client: TestClient) -> None:
    """Em localhost sobre HTTP, HSTS prenderia o navegador num HTTPS que não existe."""
    assert "Strict-Transport-Security" not in client.get("/health").headers


# --- P14: força bruta no login --------------------------------------------------------------


def test_login_barra_apos_a_janela_de_tentativas(
    client: TestClient, criar_usuario: Callable[..., Usuario]
) -> None:
    criar_usuario(matricula="70001")

    for _ in range(limite.LOGIN.limite.tentativas):
        assert client.post(
            "/auth/login", json={"matricula": "70001", "senha": "errada"}
        ).status_code == 401

    barrado = client.post("/auth/login", json={"matricula": "70001", "senha": "errada"})

    assert barrado.status_code == 429
    assert int(barrado.headers["Retry-After"]) > 0


def test_o_acerto_zera_a_contagem(
    client: TestClient, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Errar duas vezes e acertar não deve deixar o contador ali, pronto para barrar depois."""
    criar_usuario(matricula="70001")
    for _ in range(2):
        client.post("/auth/login", json={"matricula": "70001", "senha": "errada"})

    autenticar("70001")

    assert limite.LOGIN.espera(limite.chave_do_pedido("testclient", "70001")) == 0


def test_o_limite_e_por_matricula_e_origem(
    client: TestClient, criar_usuario: Callable[..., Usuario]
) -> None:
    """Varrer contas diferentes da mesma origem não pode escapar do limite por matrícula."""
    criar_usuario(matricula="70001")
    criar_usuario(matricula="70002")
    for _ in range(limite.LOGIN.limite.tentativas):
        client.post("/auth/login", json={"matricula": "70001", "senha": "errada"})

    outra = client.post("/auth/login", json={"matricula": "70002", "senha": "errada"})

    # A outra matrícula ainda tem a própria janela — o limite não pune a unidade inteira...
    assert outra.status_code == 401
    # ...mas a primeira continua barrada.
    assert client.post(
        "/auth/login", json={"matricula": "70001", "senha": "errada"}
    ).status_code == 429


def test_a_janela_desliza() -> None:
    """Sem o deslize, a primeira rajada barraria a conta para sempre."""
    limitador = limite.Limitador(limite.Limite(tentativas=2, janela_segundos=60))
    for _ in range(2):
        limitador.registrar("x", agora=100.0)

    assert limitador.espera("x", agora=100.0) > 0
    assert limitador.espera("x", agora=161.0) == 0


# --- P30: conteúdo do anexo -----------------------------------------------------------------


@pytest.mark.parametrize(
    "inicio, tipo, esperado",
    [
        (b"%PDF-1.7 ...", "application/pdf", True),
        (b"\xff\xd8\xff\xe0 ...", "image/jpeg", True),
        (b"\x89PNG\r\n\x1a\n", "image/png", True),
        (b"MZ\x90\x00", "application/pdf", False),  # executável renomeado
        (b"<html>", "application/pdf", False),
        (b"%PDF-1.7", "image/png", False),  # conteúdo certo, extensão errada
        (b"%PDF-1.7", "application/zip", False),  # tipo desconhecido fecha por omissão
    ],
)
def test_assinatura_do_arquivo(inicio: bytes, tipo: str, esperado: bool) -> None:
    assert confere(inicio, tipo) is esperado


# --- P47: assinar o que não se leu ----------------------------------------------------------


@pytest.fixture
def pt_para_assinar(
    client: TestClient, db: Session,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> dict:
    unidade = Unidade(
        nome="FPSO Alfa", identificador_operacional="FPSO-A", tipo=TipoUnidade.FPSO
    )
    db.add(unidade)
    db.flush()
    area = Area(unidade_id=unidade.id, nome="Convés", codigo="CV")
    modelo = ModeloPT(tipo_trabalho=TipoTrabalho.TRABALHO_A_QUENTE, nome="quente", campos=[])
    db.add_all([area, modelo])
    db.commit()

    criar_usuario(matricula="70001", unidade_id=unidade.id)
    dono = autenticar("70001")
    inicio = agora_utc()
    pt = client.post(
        "/pts",
        headers=dono,
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
    return {"pt": pt, "dono": dono}


def test_assinar_documento_que_mudou_depois_da_leitura_e_recusado(
    client: TestClient, db: Session, pt_para_assinar: dict
) -> None:
    """Assinar é declarar que se leu. Se o documento mudou no meio, a assinatura seria de
    outra coisa — e o hash gravado na trilha registraria uma concordância que não houve.
    """
    pt = pt_para_assinar["pt"]
    lido_em = pt["atualizado_em"]

    # A PT muda depois da leitura.
    db.get(PermissaoTrabalho, pt["id"]).descricao = "Escopo ampliado"
    db.commit()

    resposta = client.post(
        f"/pts/{pt['id']}/transicoes",
        headers=pt_para_assinar["dono"],
        json={"destino": "VALIDACAO", "visto_em": lido_em},
    )

    assert resposta.status_code == 409
    assert {p["codigo"] for p in resposta.json()["detail"]} == {"documento_alterado"}
    db.expire_all()
    assert db.get(PermissaoTrabalho, pt["id"]).estado == EstadoPT.RASCUNHO


def test_assinar_sobre_a_leitura_atual_passa(
    client: TestClient, db: Session, pt_para_assinar: dict
) -> None:
    pt = pt_para_assinar["pt"]

    resposta = client.post(
        f"/pts/{pt['id']}/transicoes",
        headers=pt_para_assinar["dono"],
        json={"destino": "VALIDACAO", "visto_em": pt["atualizado_em"]},
    )

    assert resposta.status_code == 200, resposta.text


def test_cliente_que_nao_informa_visto_em_continua_funcionando(
    client: TestClient, pt_para_assinar: dict
) -> None:
    """Opcional na transição, ao contrário da edição: aqui não há sobrescrita a impedir."""
    pt = pt_para_assinar["pt"]

    resposta = client.post(
        f"/pts/{pt['id']}/transicoes",
        headers=pt_para_assinar["dono"],
        json={"destino": "VALIDACAO"},
    )

    assert resposta.status_code == 200, resposta.text


# --- P3: erro sem stack ---------------------------------------------------------------------


def test_falha_inesperada_nao_devolve_stack() -> None:
    """Stack na resposta entrega caminho de arquivo, versão de biblioteca e às vezes consulta."""
    from starlette.requests import Request

    from app.main import app, falha_inesperada

    pedido = Request({"type": "http", "method": "GET", "path": "/x", "headers": []})
    resposta = falha_inesperada(pedido, RuntimeError("segredo: /caminho/do/servidor"))

    assert resposta.status_code == 500
    assert b"segredo" not in resposta.body
    assert b"caminho" not in resposta.body
    # E o handler precisa estar de fato ligado, senão o teste acima só exercita uma função.
    assert Exception in app.exception_handlers
