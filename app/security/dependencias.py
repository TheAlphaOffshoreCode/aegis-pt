"""Ligação entre o token e o pedido HTTP: quem é, o que pode, e o que enxerga."""

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import PerfilUsuario
from app.models.pessoa import Usuario
from app.security.credenciais import ler_token

# `auto_error=False` porque o padrão do HTTPBearer responde 403 quando falta credencial,
# e falta de credencial é 401.
_bearer = HTTPBearer(auto_error=False, description="Token obtido em POST /auth/login")


def _nao_autenticado() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credencial ausente ou inválida",
        headers={"WWW-Authenticate": "Bearer"},
    )


def usuario_atual(
    credencial: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Usuario:
    """Usuário autenticado, sempre relido do banco.

    Desativar alguém precisa cortar o acesso na hora, e não quando o token dele vencer.
    """
    if credencial is None:
        raise _nao_autenticado()
    try:
        payload = ler_token(credencial.credentials)
        usuario_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _nao_autenticado() from None

    usuario = db.get(Usuario, usuario_id)
    if usuario is None or not usuario.ativo:
        raise _nao_autenticado()
    return usuario


def exigir_perfis(*perfis: PerfilUsuario) -> Callable[..., Usuario]:
    """Dependência que barra quem não tem um dos perfis. `admin` passa em tudo."""

    def verificar(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if usuario.perfil != PerfilUsuario.ADMIN and usuario.perfil not in perfis:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Perfil {usuario.perfil} não autorizado para esta operação",
            )
        return usuario

    return verificar


def unidades_visiveis(usuario: Usuario) -> set[int] | None:
    """Unidades que o usuário enxerga. `None` significa todas.

    Regra 5: este filtro entra na consulta, antes de ler qualquer dado — nunca como
    peneira no resultado, que já seria vazamento com passo extra.
    """
    if usuario.perfil in (PerfilUsuario.ADMIN, PerfilUsuario.AUDITOR):
        return None
    if usuario.unidade_id is None:
        return set()
    return {usuario.unidade_id}
