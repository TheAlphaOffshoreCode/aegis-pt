"""Fixtures dos testes. O ambiente é definido antes de qualquer import de `app`."""

import os

os.environ["AEGIS_SECRET_KEY"] = "chave-de-teste-com-mais-de-trinta-e-dois-caracteres"
os.environ["AEGIS_DATABASE_URL"] = "sqlite:///./test_aegis.db"
os.environ["AEGIS_ENVIRONMENT"] = "development"

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: F401,E402  registra as tabelas no metadata
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


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
