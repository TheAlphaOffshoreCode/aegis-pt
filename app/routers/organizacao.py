"""Estrutura da operação, para as telas que precisam escolher onde o trabalho acontece."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.pessoa import Usuario
from app.schemas.organizacao import AreaRead
from app.security.dependencias import usuario_atual
from app.services import organizacao

router = APIRouter(tags=["operação"])


@router.get("/areas", response_model=list[AreaRead])
def listar_areas(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> list[AreaRead]:
    """Áreas do escopo de quem perguntou.

    Existe porque a emissão precisa de uma: `area_id` é obrigatório na PT e não havia de onde
    tirá-lo sem consultar o banco por fora.
    """
    return [AreaRead.model_validate(area) for area in organizacao.listar_areas(db, usuario)]
