"""Trocar o próprio segredo, e receber um de terceiro sem que isso vire uma janela.

O que estes testes prendem, e que nenhum outro prende: um PIN entregue pela coordenação **não
assina** até o dono trocá-lo. Sem isso, quem entrega passa a poder assinar no nome de quem
recebeu — exatamente o buraco que o PIN de assinatura existe para fechar.
"""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import PerfilUsuario, TipoUnidade
from app.models.organizacao import Unidade
from app.models.pessoa import Usuario
from app.rules.segredos import avaliar_pin, avaliar_senha
from app.security.credenciais import verificar_senha
from app.security.limite import ASSINATURA, LOGIN
from tests.conftest import PIN_DE_TESTE, SENHA_DE_TESTE

PIN_NOVO = "8362"
SENHA_NOVA = "outra-senha-boa-2026"


@pytest.fixture(autouse=True)
def _limites_zerados() -> None:
    """Os limitadores são estado em processo: sem isto um teste herda a contagem do anterior."""
    ASSINATURA._marcas.clear()
    LOGIN._marcas.clear()


@pytest.fixture
def duas_unidades(db: Session) -> tuple[int, int]:
    """Duas unidades de verdade, porque `usuario.unidade_id` é chave estrangeira.

    Passar um id inventado falha no INSERT — o `PRAGMA foreign_keys=ON` do L0 fiscalizando o
    banco de teste, que é exatamente para o que ele existe.
    """
    unidades = [
        Unidade(nome="FPSO Alfa", identificador_operacional="FPSO-A", tipo=TipoUnidade.FPSO),
        Unidade(nome="FPSO Beta", identificador_operacional="FPSO-B", tipo=TipoUnidade.FPSO),
    ]
    db.add_all(unidades)
    db.commit()
    return unidades[0].id, unidades[1].id


# --- a regra pura, sem banco e sem HTTP ---------------------------------------------------


@pytest.mark.parametrize(
    "pin",
    ["123", "123456789", "12a4", "", "45 6", "1234.5"],
)
def test_pin_fora_do_formato_e_recusado(pin: str) -> None:
    assert [p.codigo for p in avaliar_pin(pin, matricula="70001")] == ["pin_fora_do_formato"]


@pytest.mark.parametrize("pin", ["0000", "1111", "1234", "4321", "3456", "9876"])
def test_pin_previsivel_e_recusado(pin: str) -> None:
    assert "pin_previsivel" in [p.codigo for p in avaliar_pin(pin, matricula="70001")]


def test_pin_igual_a_matricula_e_recusado() -> None:
    codigos = [p.codigo for p in avaliar_pin("7051", matricula="7051")]
    assert codigos == ["pin_igual_a_matricula"]


@pytest.mark.parametrize("pin", ["8362", "4417", "90210", "13579"])
def test_pin_que_serve_nao_gera_pendencia(pin: str) -> None:
    assert avaliar_pin(pin, matricula="70001") == []


def test_senha_curta_e_recusada() -> None:
    assert [p.codigo for p in avaliar_senha("curta", matricula="70001")] == ["senha_curta"]


def test_senha_que_serve_nao_gera_pendencia() -> None:
    assert avaliar_senha(SENHA_NOVA, matricula="70001") == []


# --- trocar o próprio PIN -----------------------------------------------------------------


def test_trocar_o_proprio_pin(
    client: TestClient,
    db: Session,
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    usuario = criar_usuario(matricula="70001")
    resposta = client.post(
        "/auth/pin",
        json={"pin_atual": PIN_DE_TESTE, "pin_novo": PIN_NOVO},
        headers=autenticar("70001"),
    )

    assert resposta.status_code == 204, resposta.text
    db.expire_all()
    assert verificar_senha(PIN_NOVO, usuario.pin_hash)
    assert not verificar_senha(PIN_DE_TESTE, usuario.pin_hash)


def test_pin_atual_errado_recusa_a_troca(
    client: TestClient,
    db: Session,
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    usuario = criar_usuario(matricula="70001")
    resposta = client.post(
        "/auth/pin",
        json={"pin_atual": "9999", "pin_novo": PIN_NOVO},
        headers=autenticar("70001"),
    )

    assert resposta.status_code == 409
    assert resposta.json()["detail"][0]["codigo"] == "pin_atual_nao_confere"
    db.expire_all()
    assert verificar_senha(PIN_DE_TESTE, usuario.pin_hash), "o PIN antigo continua valendo"


def test_pin_novo_precisa_ser_diferente(
    client: TestClient,
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    criar_usuario(matricula="70001")
    resposta = client.post(
        "/auth/pin",
        json={"pin_atual": PIN_DE_TESTE, "pin_novo": PIN_DE_TESTE},
        headers=autenticar("70001"),
    )

    assert resposta.status_code == 409
    assert resposta.json()["detail"][0]["codigo"] == "pin_repetido"


def test_troca_de_pin_tem_limite_de_tentativas(
    client: TestClient,
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """O campo `pin_atual` confere um PIN, então sem limite ele é um oráculo de PIN."""
    criar_usuario(matricula="70001")
    cabecalho = autenticar("70001")
    corpo = {"pin_atual": "9999", "pin_novo": PIN_NOVO}

    for _ in range(3):
        assert client.post("/auth/pin", json=corpo, headers=cabecalho).status_code == 409

    excedido = client.post("/auth/pin", json=corpo, headers=cabecalho)
    assert excedido.status_code == 429
    assert "Retry-After" in excedido.headers


# --- trocar a própria senha ---------------------------------------------------------------


def test_trocar_a_propria_senha_e_entrar_com_ela(
    client: TestClient,
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    criar_usuario(matricula="70001")
    resposta = client.post(
        "/auth/senha",
        json={"senha_atual": SENHA_DE_TESTE, "senha_nova": SENHA_NOVA},
        headers=autenticar("70001"),
    )
    assert resposta.status_code == 204, resposta.text

    LOGIN._marcas.clear()
    antiga = client.post("/auth/login", json={"matricula": "70001", "senha": SENHA_DE_TESTE})
    nova = client.post("/auth/login", json={"matricula": "70001", "senha": SENHA_NOVA})
    assert antiga.status_code == 401
    assert nova.status_code == 200


def test_senha_nova_fraca_e_recusada(
    client: TestClient,
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    criar_usuario(matricula="70001")
    resposta = client.post(
        "/auth/senha",
        json={"senha_atual": SENHA_DE_TESTE, "senha_nova": "curta"},
        headers=autenticar("70001"),
    )
    assert resposta.status_code == 409
    assert resposta.json()["detail"][0]["codigo"] == "senha_curta"


# --- atribuir PIN a outra pessoa ----------------------------------------------------------


def test_coordenador_atribui_pin_a_quem_nao_tem(
    client: TestClient,
    db: Session,
    duas_unidades: tuple[int, int],
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    alfa, _ = duas_unidades
    coordenador = criar_usuario(
        matricula="70004", perfil=PerfilUsuario.COORDENADOR, unidade_id=alfa
    )
    sem_pin = criar_usuario(matricula="70001", unidade_id=alfa)
    sem_pin.pin_hash = ""
    db.commit()
    assert coordenador.unidade_id == sem_pin.unidade_id

    resposta = client.post(
        f"/usuarios/{sem_pin.id}/pin", json={"pin": PIN_NOVO}, headers=autenticar("70004")
    )

    assert resposta.status_code == 204, resposta.text
    db.expire_all()
    assert verificar_senha(PIN_NOVO, sem_pin.pin_hash)
    assert sem_pin.pin_precisa_troca, "PIN entregue por terceiro nasce obrigado a ser trocado"


def test_requisitante_nao_atribui_pin(
    client: TestClient,
    duas_unidades: tuple[int, int],
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    alfa, _ = duas_unidades
    criar_usuario(matricula="70004", unidade_id=alfa)
    alvo = criar_usuario(matricula="70001", unidade_id=alfa)

    resposta = client.post(
        f"/usuarios/{alvo.id}/pin", json={"pin": PIN_NOVO}, headers=autenticar("70004")
    )
    assert resposta.status_code == 403


def test_pin_de_outra_unidade_responde_404(
    client: TestClient,
    duas_unidades: tuple[int, int],
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """404 e não 403: dizer "não pode" já confirmaria que a pessoa existe."""
    alfa, beta = duas_unidades
    criar_usuario(matricula="70004", perfil=PerfilUsuario.COORDENADOR, unidade_id=alfa)
    de_fora = criar_usuario(matricula="70009", unidade_id=beta)

    resposta = client.post(
        f"/usuarios/{de_fora.id}/pin", json={"pin": PIN_NOVO}, headers=autenticar("70004")
    )
    assert resposta.status_code == 404


def test_listagem_de_pessoas_respeita_o_escopo(
    client: TestClient,
    duas_unidades: tuple[int, int],
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    alfa, beta = duas_unidades
    criar_usuario(matricula="70004", perfil=PerfilUsuario.COORDENADOR, unidade_id=alfa)
    criar_usuario(matricula="70001", unidade_id=alfa)
    criar_usuario(matricula="70009", unidade_id=beta)

    resposta = client.get("/usuarios", headers=autenticar("70004"))

    assert resposta.status_code == 200
    matriculas = {pessoa["matricula"] for pessoa in resposta.json()}
    assert matriculas == {"70004", "70001"}
    assert "70009" not in matriculas


def test_listagem_nao_devolve_hash_nenhum(
    client: TestClient,
    duas_unidades: tuple[int, int],
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    criar_usuario(
        matricula="70004", perfil=PerfilUsuario.COORDENADOR, unidade_id=duas_unidades[0]
    )

    corpo = client.get("/usuarios", headers=autenticar("70004")).text

    assert "hash" not in corpo.lower()
    assert "$argon2" not in corpo
