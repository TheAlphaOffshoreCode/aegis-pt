"""A migration precisa descrever exatamente os modelos — e saber voltar atrás."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

import app.models  # noqa: F401  registra as tabelas no metadata
from app.database import Base, engine

RAIZ = Path(__file__).resolve().parent.parent


def _banco_limpo() -> None:
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conexao:
        conexao.execute(text("DROP TABLE IF EXISTS alembic_version"))


def test_migration_reflete_os_modelos_e_desfaz_o_que_criou() -> None:
    """Modelo alterado sem migration nova falha aqui, e não em produção."""
    _banco_limpo()
    config = Config(str(RAIZ / "alembic.ini"))

    try:
        command.upgrade(config, "head")

        with engine.connect() as conexao:
            diferencas = compare_metadata(
                MigrationContext.configure(conexao), Base.metadata
            )
        assert diferencas == [], f"migration fora de sincronia com os modelos: {diferencas}"

        # `downgrade` é o que exercita o `render_as_batch`; sem ele o SQLite quebra aqui.
        command.downgrade(config, "base")
        restantes = set(inspect(engine).get_table_names()) - {"alembic_version"}
        assert restantes == set()
    finally:
        _banco_limpo()
