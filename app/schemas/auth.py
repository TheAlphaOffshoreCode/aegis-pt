"""Schemas de login e sessão."""

from pydantic import BaseModel, Field

from app.models.enums import PerfilUsuario
from app.schemas.base import ORMSchema


class LoginRequest(BaseModel):
    matricula: str = Field(min_length=1, max_length=20)
    senha: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_em_minutos: int


class SessaoRead(ORMSchema):
    """Quem está autenticado e o que ele alcança. `unidades` nulo significa todas."""

    id: int
    matricula: str
    nome: str
    perfil: PerfilUsuario
    unidade_id: int | None
    unidades: list[int] | None
