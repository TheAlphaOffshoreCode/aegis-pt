"""Fixtures dos testes. O ambiente é definido antes de qualquer import de `app`."""

import os

os.environ["AEGIS_SECRET_KEY"] = "chave-de-teste-com-mais-de-trinta-e-dois-caracteres"
os.environ["AEGIS_DATABASE_URL"] = "sqlite:///./test_aegis.db"
os.environ["AEGIS_ENVIRONMENT"] = "development"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    """Cliente HTTP contra a aplicação real."""
    return TestClient(app)
