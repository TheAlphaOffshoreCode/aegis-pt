"""Login e sessão. Só parse, autorização e delegação — nenhuma regra de negócio aqui."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.pessoa import Usuario
from app.models.tipos import agora_utc
from app.schemas.auth import LoginRequest, SessaoRead, TokenResponse
from app.security.credenciais import (
    criar_token,
    gastar_tempo_de_verificacao,
    verificar_senha,
)
from app.security.dependencias import unidades_visiveis, usuario_atual

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(dados: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Troca matrícula e senha por um token de sessão."""
    usuario = db.scalars(select(Usuario).where(Usuario.matricula == dados.matricula)).first()

    if usuario is None:
        # Gasta o mesmo tempo do caminho normal: sem isto, a duração da resposta
        # entrega quais matrículas existem.
        gastar_tempo_de_verificacao()
        raise _credencial_invalida()

    if not usuario.ativo or not verificar_senha(dados.senha, usuario.senha_hash):
        # Mensagem única de propósito: dizer "usuário inativo" já é informação demais.
        raise _credencial_invalida()

    usuario.ultimo_acesso = agora_utc()
    db.commit()

    return TokenResponse(
        access_token=criar_token(usuario.id),
        expira_em_minutos=get_settings().token_expiracao_minutos,
    )


@router.get("/eu", response_model=SessaoRead)
def eu(usuario: Usuario = Depends(usuario_atual)) -> SessaoRead:
    """Identidade e alcance de quem está autenticado."""
    alcance = unidades_visiveis(usuario)
    return SessaoRead(
        id=usuario.id,
        matricula=usuario.matricula,
        nome=usuario.nome,
        perfil=usuario.perfil,
        unidade_id=usuario.unidade_id,
        unidades=None if alcance is None else sorted(alcance),
    )


def _credencial_invalida() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Matrícula ou senha inválidos",
        headers={"WWW-Authenticate": "Bearer"},
    )
