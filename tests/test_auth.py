"""Autenticação e RBAC — cada teste fecha uma porta específica."""

from collections.abc import Callable
from datetime import timedelta

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Unidade, Usuario
from app.models.enums import PerfilUsuario, TipoUnidade
from app.models.tipos import agora_utc
from app.security.dependencias import exigir_perfis
from tests.conftest import SENHA_DE_TESTE


def _unidade(db: Session) -> Unidade:
    unidade = Unidade(
        nome="FPSO de teste", identificador_operacional="FPSO-A-01", tipo=TipoUnidade.FPSO
    )
    db.add(unidade)
    db.commit()
    return unidade


def test_login_devolve_token_e_registra_o_acesso(
    client: TestClient, db: Session, criar_usuario: Callable[..., Usuario]
) -> None:
    usuario = criar_usuario()
    assert usuario.ultimo_acesso is None

    corpo = client.post(
        "/auth/login", json={"matricula": "70001", "senha": SENHA_DE_TESTE}
    ).json()

    assert corpo["token_type"] == "bearer"
    assert corpo["expira_em_minutos"] == get_settings().token_expiracao_minutos
    db.refresh(usuario)
    assert usuario.ultimo_acesso is not None


def test_senha_errada_matricula_inexistente_e_inativo_respondem_igual(
    client: TestClient, criar_usuario: Callable[..., Usuario]
) -> None:
    """Três motivos, uma resposta. Distinguir já diria quem existe e quem foi desligado."""
    criar_usuario(matricula="70001")
    criar_usuario(matricula="70002", ativo=False)

    respostas = [
        client.post("/auth/login", json={"matricula": "70001", "senha": "errada"}),
        client.post("/auth/login", json={"matricula": "99999", "senha": SENHA_DE_TESTE}),
        client.post("/auth/login", json={"matricula": "70002", "senha": SENHA_DE_TESTE}),
    ]

    assert [r.status_code for r in respostas] == [401, 401, 401]
    assert len({r.json()["detail"] for r in respostas}) == 1


def test_senha_nunca_volta_em_resposta_nem_fica_em_texto_puro(
    client: TestClient, criar_usuario: Callable[..., Usuario]
) -> None:
    usuario = criar_usuario()
    corpo = client.post(
        "/auth/login", json={"matricula": "70001", "senha": SENHA_DE_TESTE}
    ).text

    assert SENHA_DE_TESTE not in corpo
    assert usuario.senha_hash.startswith("$argon2")
    assert SENHA_DE_TESTE not in usuario.senha_hash


def test_rota_protegida_recusa_sem_token_e_com_token_adulterado(
    client: TestClient, criar_usuario: Callable[..., Usuario]
) -> None:
    usuario = criar_usuario()
    agora = agora_utc()

    forjados = [
        jwt.encode({"sub": str(usuario.id), "exp": agora + timedelta(hours=1)},
                   "outro-segredo-completamente-diferente", algorithm="HS256"),
        jwt.encode({"sub": str(usuario.id), "exp": agora - timedelta(minutes=1)},
                   get_settings().secret_key, algorithm="HS256"),
        # `alg: none` é o clássico: sem `algorithms=[...]` explícito no decode, passaria.
        jwt.encode({"sub": str(usuario.id)}, key="", algorithm="none"),
        "nem-parece-um-token",
    ]

    assert client.get("/auth/eu").status_code == 401
    for token in forjados:
        assert client.get(
            "/auth/eu", headers={"Authorization": f"Bearer {token}"}
        ).status_code == 401


def test_desativar_usuario_corta_o_acesso_antes_do_token_vencer(
    client: TestClient,
    db: Session,
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """O token continua válido e assinado; quem manda é o estado atual no banco."""
    usuario = criar_usuario()
    cabecalho = autenticar("70001")
    assert client.get("/auth/eu", headers=cabecalho).status_code == 200

    usuario.ativo = False
    db.commit()

    assert client.get("/auth/eu", headers=cabecalho).status_code == 401


def test_escopo_limita_quem_tem_lotacao_e_libera_auditor(
    client: TestClient,
    db: Session,
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    unidade = _unidade(db)
    criar_usuario(matricula="70001", unidade_id=unidade.id)
    criar_usuario(matricula="70002", perfil=PerfilUsuario.AUDITOR)

    lotado = client.get("/auth/eu", headers=autenticar("70001")).json()
    auditor = client.get("/auth/eu", headers=autenticar("70002")).json()

    assert lotado["unidades"] == [unidade.id]
    assert auditor["unidades"] is None  # alcance global


@pytest.mark.parametrize(
    ("perfil", "esperado"),
    [
        (PerfilUsuario.TECNICO_SEGURANCA, 200),
        (PerfilUsuario.ADMIN, 200),
        (PerfilUsuario.EXECUTANTE, 403),
    ],
)
def test_exigir_perfis_barra_quem_nao_tem_o_papel(
    criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
    perfil: PerfilUsuario,
    esperado: int,
) -> None:
    protegido = FastAPI()

    @protegido.get("/analise")
    def analise(  # noqa: ANN202
        usuario: Usuario = Depends(exigir_perfis(PerfilUsuario.TECNICO_SEGURANCA)),
    ):
        return {"matricula": usuario.matricula}

    criar_usuario(matricula="70009", perfil=perfil)
    resposta = TestClient(protegido).get("/analise", headers=autenticar("70009"))

    assert resposta.status_code == esperado
