"""Painel operacional: indicadores e alertas."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import PerfilUsuario, StatusAlerta
from app.models.pessoa import Usuario
from app.schemas.auditoria import AlertaRead
from app.schemas.indicadores import IndicadoresRead, SincronizacaoRead
from app.security.dependencias import exigir_perfis, usuario_atual
from app.services import alertas, indicadores

router = APIRouter(tags=["painel"])


@router.get("/indicadores", response_model=IndicadoresRead)
def painel(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> IndicadoresRead:
    """Contagens da operação, no escopo de quem perguntou.

    Todo número é um `COUNT` do banco — nada aqui é estimado nem sai de modelo de linguagem
    (regra 2), e o escopo entra na consulta, não no resultado (regra 5).
    """
    return IndicadoresRead(**vars(indicadores.calcular(db, usuario)))


@router.get("/alertas", response_model=list[AlertaRead])
def listar_alertas(
    tipo: str | None = None,
    status: StatusAlerta | None = None,
    nivel_minimo: int | None = Query(default=None, ge=0),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> list[AlertaRead]:
    """Alertas do escopo, do nível mais alto para o mais baixo."""
    return [
        AlertaRead.model_validate(alerta)
        for alerta in alertas.listar(db, usuario, tipo, status, nivel_minimo)
    ]


@router.post("/alertas/sincronizar", response_model=SincronizacaoRead)
def sincronizar(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(
        exigir_perfis(PerfilUsuario.COORDENADOR, PerfilUsuario.OIM)
    ),
) -> SincronizacaoRead:
    """Recalcula as condições e materializa os alertas.

    Roda sobre a operação inteira, não sobre o escopo de quem chamou — um alerta que só
    existisse quando a pessoa certa clicasse não seria um alerta. Por isso a rota é restrita a
    coordenação e OIM: quem dispara não é quem lê.

    Idempotente: chamar duas vezes seguidas não abre nem escala nada. Feita para um cron
    chamar; não há daemon escondido no processo.
    """
    return SincronizacaoRead(**vars(alertas.sincronizar(db)))
