"""Fixtures dos testes. O ambiente é definido antes de qualquer import de `app`."""

import os

os.environ["AEGIS_SECRET_KEY"] = "chave-de-teste-com-mais-de-trinta-e-dois-caracteres"
os.environ["AEGIS_DATABASE_URL"] = "sqlite:///./test_aegis.db"
os.environ["AEGIS_ENVIRONMENT"] = "development"
# Uploads dos testes ficam longe da pasta real da aplicação.
os.environ["AEGIS_UPLOAD_DIR"] = "./test_uploads"

import shutil  # noqa: E402
from collections.abc import Callable, Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: F401,E402  registra as tabelas no metadata
from app.config import get_settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import PerfilUsuario  # noqa: E402
from app.models.pessoa import Usuario  # noqa: E402
from app.security.credenciais import gerar_hash  # noqa: E402

SENHA_DE_TESTE = "senha-de-teste-123"


@pytest.fixture(autouse=True)
def _uploads_limpos() -> Iterator[None]:
    """Cada teste começa e termina sem arquivo nenhum em disco."""
    destino = get_settings().upload_dir
    shutil.rmtree(destino, ignore_errors=True)
    yield
    shutil.rmtree(destino, ignore_errors=True)


@pytest.fixture
def client() -> TestClient:
    """Cliente HTTP contra a aplicação real."""
    return TestClient(app)


@pytest.fixture
def db() -> Iterator[Session]:
    """Banco vazio por teste: as tabelas nascem e morrem dentro do próprio teste."""
    Base.metadata.create_all(bind=engine)
    sessao = SessionLocal()
    try:
        yield sessao
    finally:
        sessao.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def criar_usuario(db: Session) -> Callable[..., Usuario]:
    """Cria um usuário com senha conhecida, pronto para autenticar."""

    def _criar(
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
            senha_hash=gerar_hash(SENHA_DE_TESTE),
        )
        db.add(usuario)
        db.commit()
        return usuario

    return _criar


@pytest.fixture
def autenticar(client: TestClient) -> Callable[[str], dict[str, str]]:
    """Faz login e devolve o cabeçalho `Authorization` pronto."""

    def _autenticar(matricula: str) -> dict[str, str]:
        resposta = client.post(
            "/auth/login", json={"matricula": matricula, "senha": SENHA_DE_TESTE}
        )
        assert resposta.status_code == 200, resposta.text
        return {"Authorization": f"Bearer {resposta.json()['access_token']}"}

    return _autenticar
