"""As pessoas, vistas por quem entrega credencial de assinatura.

Separado de `/auth` porque a pergunta é outra. `/auth` é sobre **mim**: minha sessão, meus
segredos, e tudo ali é autorizado por eu saber o segredo atual. Aqui é sobre **outra pessoa**, e
o que autoriza é o perfil — coordenação e OIM entregam PIN a quem está sob eles.

Não é cadastro de pessoas: criar, desativar e mudar perfil ou lotação continuam fora, no seed.
Mexer em perfil é mexer em escopo e em quem assina o quê, e isso é loop próprio (P58).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import PerfilUsuario
from app.models.pessoa import Usuario
from app.schemas.auth import AtribuirPinRequest, PessoaRead
from app.security.dependencias import exigir_perfis
from app.services import contas

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

# Quem entrega PIN. `admin` passa em tudo por decisão do L2, e não é acréscimo aqui.
PERFIS_QUE_ATRIBUEM = (PerfilUsuario.COORDENADOR, PerfilUsuario.OIM)


@router.get("", response_model=list[PessoaRead])
def listar(
    db: Session = Depends(get_db),
    solicitante: Usuario = Depends(exigir_perfis(*PERFIS_QUE_ATRIBUEM)),
) -> list[Usuario]:
    """As pessoas no alcance de quem perguntou, com o estado do PIN de cada uma."""
    return contas.pessoas_no_escopo(db, solicitante)


@router.post("/{usuario_id}/pin", status_code=status.HTTP_204_NO_CONTENT)
def atribuir_pin(
    usuario_id: int,
    dados: AtribuirPinRequest,
    db: Session = Depends(get_db),
    solicitante: Usuario = Depends(exigir_perfis(*PERFIS_QUE_ATRIBUEM)),
) -> None:
    """Entrega um PIN a quem não tem ou perdeu. Ele nasce obrigado a ser trocado.

    Sem exceção para si mesmo: uma coordenadora que esqueceu o próprio PIN o redefine por aqui
    e, como qualquer outra pessoa, precisa trocá-lo antes de assinar. Abrir exceção seria dar a
    um perfil um PIN que assina sem ninguém mais saber que ele mudou.
    """
    alvo = contas.obter_pessoa(db, usuario_id, solicitante)
    if alvo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")
    contas.atribuir_pin(db, alvo, pin=dados.pin)
