"""Aceite do L0: o serviço sobe, o health check responde e o segredo é obrigatório."""

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.config import Settings
from app.database import SessionLocal, engine


def test_health_responde_200(client):
    resposta = client.get("/health")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ok"
    assert resposta.json()["database"] == "ok"


def test_openapi_disponivel(client):
    assert client.get("/openapi.json").status_code == 200


def test_shell_do_pwa_e_servido(client):
    resposta = client.get("/")
    assert resposta.status_code == 200
    assert "AEGIS PT" in resposta.text


def test_secret_key_curta_e_rejeitada():
    with pytest.raises(ValidationError):
        Settings(secret_key="curta")


@pytest.mark.skipif(
    engine.dialect.name != "sqlite",
    reason="O PRAGMA é o mecanismo do SQLite; no PostgreSQL a chave estrangeira não é opcional.",
)
def test_foreign_keys_ativas_no_sqlite():
    """Sem o PRAGMA, o SQLite aceita referência órfã e o modelo mente sobre a integridade."""
    with SessionLocal() as db:
        assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
