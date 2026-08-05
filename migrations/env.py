"""Ambiente do Alembic. A URL do banco vem do settings, nunca do alembic.ini."""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models  # noqa: F401,E402  registra os modelos no metadata
from app.config import get_settings  # noqa: E402
from app.database import Base, engine  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
_is_sqlite = engine.dialect.name == "sqlite"


def run_migrations_offline() -> None:
    """Gera o SQL da migration sem abrir conexão."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Aplica a migration na conexão real."""
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite não faz ALTER TABLE completo; sem batch, downgrade de coluna quebra.
            render_as_batch=_is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
