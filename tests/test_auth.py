"""Autenticação e RBAC — cada teste fecha uma porta específica."""

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
from app.security.credenciais import gerar_hash
from app.security.dependencias import exigir_perfis

SENHA = "senha-de-teste-123"


def _usuario(
    db: Session,
    matricula: str = "70001",
    perfil: PerfilUsuario = PerfilUsuario.REQUISITANTE,
    unidade_id: int | None = None,
    ativo: bool = True,
) -> Usuario:
    usuario = Usuario(
        matricula=matricula,
        nome=f"Usuário {matricula}",
        email=f"{matricula}@exemplo.com",
        empresa="Alpha Offshore",
        cargo="Cargo",
        perfil=perfil,
        ativo=ativo,
        unidade_id=unidade_id,
        senha_hash=gerar_hash(SENHA),
    )
    db.add(usuario)
    db.commit()
    return usuario


def _unidade(db: Session) -> Unidade:
    unidade = Unidade(
        nome="FPSO de teste", identificador_operacional="FPSO-A-01", tipo=TipoUnidade.FPSO
    )
    db.add(unidade)
    db.commit()
    return unidade


def _token_de(client: TestClient, matricula: str) -> str:
    resposta = client.post("/auth/login", json={"matricula": matricula, "senha": SENHA})
    assert resposta.status_code == 200
    return resposta.json()["access_token"]


def test_login_devolve_token_e_registra_o_acesso(client: TestClient, db: Session) -> None:
    usuario = _usuario(db)
    assert usuario.ultimo_acesso is None

    corpo = client.post(
        "/auth/login", json={"matricula": "70001", "senha": SENHA}
    ).json()

    assert corpo["token_type"] == "bearer"
    assert corpo["expira_em_minutos"] == get_settings().token_expiracao_minutos
    db.refresh(usuario)
    assert usuario.ultimo_acesso is not None


def test_senha_errada_matricula_inexistente_e_inativo_respondem_igual(
    client: TestClient, db: Session
) -> None:
    """Três motivos, uma resposta. Distinguir já diria quem existe e quem foi desligado."""
    _usuario(db, matricula="70001")
    _usuario(db, matricula="70002", ativo=False)

    respostas = [
        client.post("/auth/login", json={"matricula": "70001", "senha": "errada"}),
        client.post("/auth/login", json={"matricula": "99999", "senha": SENHA}),
        client.post("/auth/login", json={"matricula": "70002", "senha": SENHA}),
    ]

    assert [r.status_code for r in respostas] == [401, 401, 401]
    assert len({r.json()["detail"] for r in respostas}) == 1


def test_senha_nunca_volta_em_resposta_nem_fica_em_texto_puro(
    client: TestClient, db: Session
) -> None:
    usuario = _usuario(db)
    corpo = client.post("/auth/login", json={"matricula": "70001", "senha": SENHA}).text

    assert SENHA not in corpo
    assert usuario.senha_hash.startswith("$argon2")
    assert SENHA not in usuario.senha_hash


def test_rota_protegida_recusa_sem_token_e_com_token_adulterado(
    client: TestClient, db: Session
) -> None:
    usuario = _usuario(db)
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
        assert client.get("/auth/eu", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_desativar_usuario_corta_o_acesso_antes_do_token_vencer(
    client: TestClient, db: Session
) -> None:
    """O token continua válido e assinado; quem manda é o estado atual no banco."""
    usuario = _usuario(db)
    token = _token_de(client, "70001")
    cabecalho = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/eu", headers=cabecalho).status_code == 200

    usuario.ativo = False
    db.commit()

    assert client.get("/auth/eu", headers=cabecalho).status_code == 401


def test_escopo_limita_quem_tem_lotacao_e_libera_auditor(
    client: TestClient, db: Session
) -> None:
    unidade = _unidade(db)
    _usuario(db, matricula="70001", unidade_id=unidade.id)
    _usuario(db, matricula="70002", perfil=PerfilUsuario.AUDITOR)

    lotado = client.get(
        "/auth/eu", headers={"Authorization": f"Bearer {_token_de(client, '70001')}"}
    ).json()
    auditor = client.get(
        "/auth/eu", headers={"Authorization": f"Bearer {_token_de(client, '70002')}"}
    ).json()

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
    client: TestClient, db: Session, perfil: PerfilUsuario, esperado: int
) -> None:
    protegido = FastAPI()

    @protegido.get("/analise")
    def analise(  # noqa: ANN202
        usuario: Usuario = Depends(exigir_perfis(PerfilUsuario.TECNICO_SEGURANCA)),
    ):
        return {"matricula": usuario.matricula}

    _usuario(db, matricula="70009", perfil=perfil)
    token = _token_de(client, "70009")

    resposta = TestClient(protegido).get(
        "/analise", headers={"Authorization": f"Bearer {token}"}
    )

    assert resposta.status_code == esperado
