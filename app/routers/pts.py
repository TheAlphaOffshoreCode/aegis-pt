"""Endpoints da PT. Só parse, autorização e delegação — a regra vive em `app/rules`."""

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.trilha import Contexto
from app.database import get_db
from app.models.auditoria import AuditEvent
from app.models.enums import EstadoPT, PerfilUsuario, TipoAnexo, TipoTrabalho
from app.models.permissao import Anexo, ModeloPT, PermissaoTrabalho, PTVersao
from app.models.pessoa import Usuario
from app.rules.pendencias import ConflitoDeNegocio, bloqueiam, bloqueio
from app.schemas.auditoria import AuditEventRead, CompensacaoRequest, TrilhaRead
from app.schemas.permissao import (
    AnexoRead,
    AvaliacaoRead,
    DossieRead,
    FiltroPT,
    ModeloPTRead,
    PaginaDePTs,
    PermissaoTrabalhoCreate,
    PermissaoTrabalhoRead,
    PermissaoTrabalhoUpdate,
    PTVersaoRead,
    TransicaoDisponivel,
    TransicaoRequest,
)
from app.security.assinante import assinante_alcanca, identificar_assinante
from app.security.dependencias import exigir_perfis, usuario_atual
from app.services import anexos, auditoria, dossie, permissoes
from app.services.transicoes import executar_transicao, transicoes_disponiveis

router = APIRouter(prefix="/pts", tags=["permissões de trabalho"])


# Estas duas vêm antes de `/{pt_id}`: registradas depois, nunca seriam alcançadas, porque o
# Starlette casa na ordem de registro — e o `pt_id` responderia 422 tentando ler "modelos" como
# inteiro.
@router.get("/modelos", response_model=list[ModeloPTRead])
def modelos_ativos(
    db: Session = Depends(get_db),
    _: Usuario = Depends(usuario_atual),
) -> list[ModeloPT]:
    """Um modelo ativo por tipo de trabalho, o de maior versão.

    A tela de emissão monta o seletor de tipo com isto, e não com a lista de `TipoTrabalho` —
    tipo sem modelo cadastrado é um beco, em que a pessoa escolhe, o formulário não carrega e a
    emissão morre ali. Oferecer só o que dá para emitir é o próprio seletor dizendo a verdade.
    """
    modelos = db.scalars(
        select(ModeloPT)
        .where(ModeloPT.ativo.is_(True))
        .order_by(ModeloPT.tipo_trabalho, ModeloPT.versao.desc())
    )
    por_tipo: dict[TipoTrabalho, ModeloPT] = {}
    for modelo in modelos:
        por_tipo.setdefault(modelo.tipo_trabalho, modelo)
    return list(por_tipo.values())


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


@router.get("", response_model=PaginaDePTs)
def listar(
    filtro: FiltroPT = Depends(),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> PaginaDePTs:
    """Busca paginada. O escopo entra na consulta e na contagem, nunca no resultado."""
    total, itens = permissoes.buscar_pts(db, usuario, filtro)
    return PaginaDePTs(
        total=total, limite=filtro.limite, deslocamento=filtro.deslocamento, itens=itens
    )


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
    operador: Usuario = Depends(usuario_atual),
) -> PermissaoTrabalho:
    """Move a PT de estado, assinando e registrando na trilha.

    Duas identidades, de propósito. O **operador** é quem abriu a sessão no aparelho: é o
    escopo dele que decide qual PT pode ser lida (regra 5). O **assinante** é quem prova a
    identidade agora, com o PIN, e é o nome que vai para a assinatura e para a trilha.

    Num tablet compartilhado eles quase nunca são a mesma pessoa, e tratá-los como um só era
    registrar autoria falsa em documento que autoriza trabalho de risco.
    """
    pt = _pt_no_escopo(db, pt_id, operador)

    ator = operador
    autoria_confirmada = False
    if dados.matricula and dados.pin:
        ator = identificar_assinante(
            db,
            matricula=dados.matricula,
            pin=dados.pin,
            ip=request.client.host if request.client else None,
        )
        # O PIN não é atalho por fora do escopo: quem assina precisa alcançar a unidade da PT,
        # como precisaria para simplesmente lê-la.
        if not assinante_alcanca(ator, pt.unidade_id):
            raise ConflitoDeNegocio(
                [
                    bloqueio(
                        "assinante_fora_do_escopo",
                        f"{ator.nome} não está lotado na unidade desta PT e não pode assiná-la",
                        campo="matricula",
                    )
                ]
            )
        autoria_confirmada = True

    return executar_transicao(
        db,
        pt,
        dados.destino,
        ator,
        motivo=dados.motivo,
        visto_em=dados.visto_em,
        contexto=_contexto(request, dados.geolocalizacao),
        autoria_confirmada=autoria_confirmada,
    )


@router.get("/{pt_id}/versoes", response_model=list[PTVersaoRead])
def versoes(
    pt_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> list[PTVersao]:
    """Histórico de versões da PT, com o retrato e o diff de cada revisão."""
    return list(dossie.versoes_da_pt(db, _pt_no_escopo(db, pt_id, usuario)))


@router.get("/{pt_id}/dossie", response_model=DossieRead)
def dossie_da_pt(
    pt_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> dict:
    """A PT inteira: versões, assinaturas, anexos, equipe, trilha conferida e pendências."""
    return dossie.montar(db, _pt_no_escopo(db, pt_id, usuario))


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


@router.post(
    "/{pt_id}/anexos", response_model=AnexoRead, status_code=status.HTTP_201_CREATED
)
def anexar(
    pt_id: int,
    request: Request,
    arquivo: UploadFile,
    tipo: TipoAnexo = Form(...),
    valido_ate: date | None = Form(default=None),
    db: Session = Depends(get_db),
    autor: Usuario = Depends(usuario_atual),
) -> Anexo:
    """Envia um documento para a PT. O hash é calculado aqui, sobre o conteúdo recebido."""
    return anexos.anexar(
        db,
        _pt_no_escopo(db, pt_id, autor),
        arquivo,
        tipo,
        autor,
        valido_ate,
        _contexto(request, None),
    )


@router.get("/{pt_id}/anexos", response_model=list[AnexoRead])
def listar_anexos(
    pt_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> list[Anexo]:
    """Documentos da PT. O conteúdo vem por outra rota; aqui só os metadados."""
    return list(_pt_no_escopo(db, pt_id, usuario).anexos)


@router.get("/{pt_id}/anexos/{anexo_id}/conteudo")
def baixar_anexo(
    pt_id: int,
    anexo_id: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> FileResponse:
    """Entrega o arquivo — sempre como download, nunca renderizado no navegador."""
    pt = _pt_no_escopo(db, pt_id, usuario)
    anexo = next((a for a in pt.anexos if a.id == anexo_id), None)
    if anexo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Anexo não encontrado nesta PT"
        )

    return FileResponse(
        anexos.caminho_absoluto(anexo),
        # Tipo do nosso mapa, não o que o cliente declarou no upload.
        media_type=anexos.EXTENSOES_PERMITIDAS[Path(anexo.caminho).suffix.lower()],
        # O `Content-Disposition` sai daqui, e não de um header montado à mão: o nome veio do
        # cliente, e concatená-lo num header seria deixar aspas e quebra de linha entrarem.
        # O Starlette já responde `attachment` e faz o encoding do nome.
        filename=anexo.nome_arquivo,
        # Anexo é conteúdo de terceiro: o navegador não pode adivinhar o tipo e executá-lo.
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.delete("/{pt_id}/anexos/{anexo_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_anexo(
    pt_id: int,
    anexo_id: int,
    request: Request,
    db: Session = Depends(get_db),
    autor: Usuario = Depends(usuario_atual),
) -> None:
    """Remove um anexo do rascunho. Depois que a PT circulou, o anexo é registro."""
    pt = _pt_no_escopo(db, pt_id, autor)
    anexo = next((a for a in pt.anexos if a.id == anexo_id), None)
    if anexo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Anexo não encontrado nesta PT"
        )
    anexos.remover(db, pt, anexo, autor, _contexto(request, None))


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
