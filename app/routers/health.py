"""Health check: prova que o processo está de pé e que o banco responde."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db

router = APIRouter(tags=["sistema"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Retorna 200 com o estado do serviço e da conexão com o banco."""
    settings = get_settings()
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "database": "ok",
    }
