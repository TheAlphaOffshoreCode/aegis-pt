"""Login e sessão. Só parse, autorização e delegação — nenhuma regra de negócio aqui."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.pessoa import Usuario
from app.models.tipos import agora_utc
from app.schemas.auth import (
    LoginRequest,
    SessaoRead,
    TokenResponse,
    TrocaPinRequest,
    TrocaSenhaRequest,
)
from app.security.credenciais import (
    criar_token,
    gastar_tempo_de_verificacao,
    verificar_senha,
)
from app.security.dependencias import unidades_visiveis, usuario_atual
from app.security.limite import ASSINATURA, LOGIN, chave_do_pedido
from app.services import contas

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    dados: LoginRequest, request: Request, db: Session = Depends(get_db)
) -> TokenResponse:
    """Troca matrícula e senha por um token de sessão."""
    chave = _chave(request, dados.matricula)
    LOGIN.exigir(chave)
    LOGIN.registrar(chave)

    usuario = db.scalars(select(Usuario).where(Usuario.matricula == dados.matricula)).first()

    if usuario is None:
        # Gasta o mesmo tempo do caminho normal: sem isto, a duração da resposta
        # entrega quais matrículas existem.
        gastar_tempo_de_verificacao()
        raise _credencial_invalida()

    if not usuario.ativo or not verificar_senha(dados.senha, usuario.senha_hash):
        # Mensagem única de propósito: dizer "usuário inativo" já é informação demais.
        raise _credencial_invalida()

    # Só o acerto zera a contagem: erro seguido de acerto não deveria abrir a porta para uma
    # nova rajada de tentativas.
    LOGIN.liberar(chave)
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
        pin_precisa_troca=usuario.pin_precisa_troca,
        tem_pin=usuario.tem_pin,
    )


@router.post("/senha", status_code=status.HTTP_204_NO_CONTENT)
def trocar_senha(
    dados: TrocaSenhaRequest,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> None:
    """Troca a própria senha de sessão.

    Vai atrás do mesmo limitador do login, e pela mesma razão: o campo `senha_atual` confere
    uma senha, então sem limite ele seria um oráculo de senha com um token válido na mão.
    """
    chave = _chave(request, usuario.matricula)
    LOGIN.exigir(chave)
    LOGIN.registrar(chave)
    contas.trocar_senha(
        db, usuario, senha_atual=dados.senha_atual, senha_nova=dados.senha_nova
    )
    LOGIN.liberar(chave)


@router.post("/pin", status_code=status.HTTP_204_NO_CONTENT)
def trocar_pin(
    dados: TrocaPinRequest,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> None:
    """Troca o próprio PIN de assinatura.

    É o único caminho que funciona com `pin_precisa_troca` ligado — de propósito: o PIN que a
    coordenação entrega abre apenas a própria substituição.
    """
    chave = _chave(request, usuario.matricula)
    # O mesmo limitador da assinatura, porque é o mesmo segredo sendo adivinhado. Contagem
    # separada aqui daria ao atacante um segundo balcão para tentar o mesmo PIN.
    ASSINATURA.exigir(chave)
    ASSINATURA.registrar(chave)
    contas.trocar_pin(db, usuario, pin_atual=dados.pin_atual, pin_novo=dados.pin_novo)
    ASSINATURA.liberar(chave)


def _chave(request: Request, matricula: str) -> str:
    """Chave do limitador: por origem **e** por identidade.

    Só por IP puniria a unidade inteira atrás de um NAT; só por matrícula deixaria alguém varrer
    contas diferentes da mesma origem. As três rotas com limite usam esta mesma chave.
    """
    return chave_do_pedido(None if request.client is None else request.client.host, matricula)


def _credencial_invalida() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Matrícula ou senha inválidos",
        headers={"WWW-Authenticate": "Bearer"},
    )
