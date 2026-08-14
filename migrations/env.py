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
        bruta = connection.connection.dbapi_connection if _is_sqlite else None
        if bruta is not None:
            # Batch mode recria a tabela: cria uma temporária, copia, **apaga a original** e
            # renomeia. Com `foreign_keys=ON` — que `app/database.py` liga em toda conexão —
            # o DROP de uma tabela referenciada é recusado, a migração aborta no meio e deixa
            # uma `_alembic_tmp_*` para trás; a tentativa seguinte morre com "table already
            # exists", que não diz nada sobre a causa real.
            #
            # `audit_event` referencia a si mesma (evento compensado) e foi a primeira a bater
            # nisso. Desligar aqui é o procedimento recomendado para batch no SQLite.
            #
            # Vai na conexão do driver de propósito: o PRAGMA é **ignorado em silêncio** dentro
            # de uma transação, e qualquer `execute` pelo SQLAlchemy abriria uma.
            bruta.execute("PRAGMA foreign_keys=OFF")

        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                # SQLite não faz ALTER TABLE completo; sem batch, downgrade de coluna quebra.
                render_as_batch=_is_sqlite,
            )
            with context.begin_transaction():
                context.run_migrations()

            if bruta is not None:
                # A integridade é reconferida agora, com o esquema novo. Uma migration que
                # deixou referência órfã tem de falhar aqui, alto, e não meses depois numa
                # consulta.
                orfas = bruta.execute("PRAGMA foreign_key_check").fetchall()
                if orfas:
                    raise RuntimeError(f"A migration deixou referências órfãs: {orfas}")
        finally:
            if bruta is not None:
                # Religar **sempre**, e é o `finally` que importa: `tests/test_migration.py`
                # roda o Alembic dentro do processo do pytest, na mesma engine. Sem isto a
                # conexão volta ao pool com a fiscalização desligada e o próximo teste a
                # herda — foi assim que o `ON DELETE RESTRICT` de `audit_event`, que é a
                # regra 4 no nível do esquema, deixou de valer sem ninguém tocar nele.
                bruta.execute("PRAGMA foreign_keys=ON")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
