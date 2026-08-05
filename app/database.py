"""Engine, sessão e Base declarativa. Mesmo código para SQLite e PostgreSQL."""

from collections.abc import Iterator

from sqlalchemy import create_engine, event
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


class Base(DeclarativeBase):
    """Base declarativa de todos os modelos."""


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
