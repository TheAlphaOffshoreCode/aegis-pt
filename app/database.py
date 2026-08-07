"""Engine, sessão e Base declarativa. Mesmo código para SQLite e PostgreSQL."""

from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    # SQLite abre a conexão presa à thread que a criou; o TestClient usa outra.
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# Nomes previsíveis de constraint. O SQLite não faz ALTER TABLE, então o Alembic recria a
# tabela em batch — e uma constraint anônima não sobrevive à recriação.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base declarativa de todos os modelos."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


if _is_sqlite:
    # Registrado nesta engine, e não na classe Engine, para não afetar conexões alheias.
    @event.listens_for(engine, "connect")
    def _ativar_foreign_keys(dbapi_connection, connection_record) -> None:
        """SQLite ignora chave estrangeira por padrão; sem isto o modelo não é fiscalizado."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Iterator[Session]:
    """Dependência FastAPI: uma sessão por requisição, sempre fechada."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
