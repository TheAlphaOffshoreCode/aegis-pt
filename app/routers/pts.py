"""Endpoints da PT. Só parse, autorização e delegação — a regra vive em `app/rules`."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.trilha import Contexto
from app.database import get_db
from app.models.auditoria import AuditEvent
from app.models.enums import EstadoPT, PerfilUsuario, TipoTrabalho
from app.models.permissao import ModeloPT, PermissaoTrabalho
from app.models.pessoa import Usuario
from app.rules.pendencias import bloqueiam
from app.schemas.auditoria import AuditEventRead, CompensacaoRequest, TrilhaRead
from app.schemas.permissao import (
    AvaliacaoRead,
    ModeloPTRead,
    PermissaoTrabalhoCreate,
    PermissaoTrabalhoRead,
    PermissaoTrabalhoUpdate,
    TransicaoDisponivel,
    TransicaoRequest,
)
from app.security.dependencias import exigir_perfis, usuario_atual
from app.services import auditoria, permissoes
from app.services.transicoes import executar_transicao, transicoes_disponiveis

router = APIRouter(prefix="/pts", tags=["permissões de trabalho"])


# Declarado antes de `/{pt_id}`: registrada depois, esta rota nunca seria alcançada,
# porque o Starlette casa na ordem de registro.
@router.get("/modelos/{tipo_trabalho}", response_model=ModeloPTRead)
def modelo_do_tipo(
    tipo_trabalho: TipoTrabalho,
    db: Session = Depends(get_db),
    _: Usuario = Depends(usuario_atual),
) -> ModeloPT:
    """Definição do formulário para um tipo de trabalho — é com ela que o PWA monta a tela."""
    modelo = db.scalars(
        select(ModeloPT)
        .where(ModeloPT.tipo_trabalho == tipo_trabalho, ModeloPT.ativo.is_(True))
        .order_by(ModeloPT.versao.desc())
    ).first()
    if modelo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nenhum modelo ativo para {tipo_trabalho}",
        )
    return modelo


@router.post("", response_model=PermissaoTrabalhoRead, status_code=status.HTTP_201_CREATED)
def criar(
    dados: PermissaoTrabalhoCreate,
    request: Request,
    db: Session = Depends(get_db),
    autor: Usuario = Depends(exigir_perfis(*permissoes.PERFIS_QUE_EMITEM)),
) -> PermissaoTrabalho:
    """Abre uma PT em rascunho."""
    return permissoes.criar_pt(db, dados, autor, _contexto(request, None))


@router.get("", response_model=list[PermissaoTrabalhoRead])
def listar(
    estado: EstadoPT | None = None,
    tipo_trabalho: TipoTrabalho | None = None,
    vigentes_em: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> list[PermissaoTrabalho]:
    """PTs que o usuário alcança. O escopo entra na consulta, não no resultado."""
    return list(permissoes.listar_pts(db, usuario, estado, tipo_trabalho, vigentes_em))


@router.get("/{pt_id}", response_model=PermissaoTrabalhoRead)
def obter(
    pt_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> PermissaoTrabalho:
    """PT por id, desde que dentro do escopo."""
    return _pt_no_escopo(db, pt_id, usuario)


@router.patch("/{pt_id}", response_model=PermissaoTrabalhoRead)
def atualizar(
    pt_id: int,
    dados: PermissaoTrabalhoUpdate,
    request: Request,
    db: Session = Depends(get_db),
    autor: Usuario = Depends(exigir_perfis(*permissoes.PERFIS_QUE_EMITEM)),
) -> PermissaoTrabalho:
    """Corrige um rascunho. Fora de `RASCUNHO` a mudança é transição, e transição é do L5."""
    return permissoes.atualizar_pt(
        db, _pt_no_escopo(db, pt_id, autor), dados, autor, _contexto(request, None)
    )


@router.get("/{pt_id}/pendencias", response_model=AvaliacaoRead)
def pendencias(
    pt_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> AvaliacaoRead:
    """O que impede esta PT de ser liberada, segundo o motor de regras.

    Consulta, não decisão: responde 200 mesmo cheia de pendência. Quem impede a transição é o
    L5, usando este mesmo veredito.
    """
    pt = _pt_no_escopo(db, pt_id, usuario)
    encontradas = permissoes.pendencias_da_pt(db, pt)
    return AvaliacaoRead(
        pt_id=pt.id,
        numero=pt.numero,
        liberavel=not bloqueiam(encontradas),
        pendencias=[p.como_dict() for p in encontradas],
    )


@router.get("/{pt_id}/transicoes", response_model=list[TransicaoDisponivel])
def transicoes(
    pt_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> list[dict]:
    """Passos possíveis agora, e quais deles este usuário pode dar."""
    return transicoes_disponiveis(_pt_no_escopo(db, pt_id, usuario), usuario)


@router.post("/{pt_id}/transicoes", response_model=PermissaoTrabalhoRead)
def transicionar(
    pt_id: int,
    dados: TransicaoRequest,
    request: Request,
    db: Session = Depends(get_db),
    ator: Usuario = Depends(usuario_atual),
) -> PermissaoTrabalho:
    """Move a PT de estado, assinando e registrando na trilha."""
    return executar_transicao(
        db,
        _pt_no_escopo(db, pt_id, ator),
        dados.destino,
        ator,
        motivo=dados.motivo,
        contexto=_contexto(request, dados.geolocalizacao),
    )


@router.get("/{pt_id}/trilha", response_model=TrilhaRead)
def trilha(
    pt_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> TrilhaRead:
    """A trilha da PT, já conferida elo a elo."""
    pt = _pt_no_escopo(db, pt_id, usuario)
    eventos, quebras = auditoria.conferir(db, pt)
    return TrilhaRead(
        pt_id=pt.id,
        numero=pt.numero,
        integra=not quebras,
        quebras=[q.como_dict() for q in quebras],
        eventos=eventos,
    )


@router.post(
    "/{pt_id}/trilha/{evento_id}/compensacao",
    response_model=AuditEventRead,
    status_code=status.HTTP_201_CREATED,
)
def compensar_evento(
    pt_id: int,
    evento_id: int,
    dados: CompensacaoRequest,
    request: Request,
    db: Session = Depends(get_db),
    ator: Usuario = Depends(
        exigir_perfis(PerfilUsuario.COORDENADOR, PerfilUsuario.OIM)
    ),
) -> AuditEvent:
    """Corrige um registro da trilha sem apagá-lo: acrescenta um evento que o referencia."""
    return auditoria.compensar(
        db,
        _pt_no_escopo(db, pt_id, ator),
        evento_id,
        ator,
        dados.motivo,
        _contexto(request, dados.geolocalizacao),
    )


def _contexto(request: Request, geolocalizacao: str | None) -> Contexto:
    """Dispositivo e IP vêm da requisição; só a geolocalização o cliente informa."""
    return Contexto(
        dispositivo=request.headers.get("user-agent"),
        ip=None if request.client is None else request.client.host,
        geolocalizacao=geolocalizacao,
    )


def _pt_no_escopo(db: Session, pt_id: int, usuario: Usuario) -> PermissaoTrabalho:
    """404 também quando a PT existe mas está fora do escopo — 403 já confirmaria que existe."""
    pt = permissoes.obter_pt(db, pt_id, usuario)
    if pt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PT não encontrada")
    return pt
