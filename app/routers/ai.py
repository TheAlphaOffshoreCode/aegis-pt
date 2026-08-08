"""Consulta em linguagem natural e proposta de rascunho."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.ai import agente, rascunho
from app.audit.trilha import Contexto
from app.database import get_db
from app.models.pessoa import Usuario
from app.schemas.ai import (
    ConsultaRequest,
    ConsultaResponse,
    RascunhoRequest,
    RascunhoResponse,
)
from app.security.dependencias import usuario_atual

router = APIRouter(prefix="/ai", tags=["ia"])

SEM_CHAVE = "Consulta por IA indisponível: chave da Claude API não configurada"


@router.post("/consulta", response_model=ConsultaResponse)
def consulta(
    dados: ConsultaRequest,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> ConsultaResponse:
    """Responde em linguagem natural, citando as PTs consultadas.

    O escopo de quem pergunta entra nas ferramentas antes da chamada ao modelo, e as fontes
    saem do que o banco devolveu — não do que a resposta afirma ter consultado.
    """
    try:
        resultado = agente.responder(db, usuario, dados.pergunta)
    except agente.IAIndisponivel:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, SEM_CHAVE) from None

    return ConsultaResponse(
        resposta=resultado.texto,
        fontes=resultado.fontes,
        iteracoes=resultado.iteracoes,
        tokens_entrada=resultado.tokens_entrada,
        tokens_saida=resultado.tokens_saida,
    )


@router.post("/rascunho", response_model=RascunhoResponse, status_code=status.HTTP_201_CREATED)
def propor_rascunho(
    dados: RascunhoRequest,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> RascunhoResponse:
    """Cria uma PT em `RASCUNHO` a partir de uma descrição em texto livre.

    A PT nasce pelo mesmo caminho de qualquer outra: mesma validação, mesma numeração, mesma
    trilha e o mesmo fluxo de assinatura pela frente. Propor não é aprovar — o que a IA
    escreve é texto, e o formulário continua sendo preenchido a bordo.
    """
    contexto = Contexto(
        dispositivo=request.headers.get("user-agent"),
        ip=None if request.client is None else request.client.host,
    )
    try:
        resultado = rascunho.propor(db, usuario, dados.model_dump(), contexto=contexto)
    except agente.IAIndisponivel:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, SEM_CHAVE) from None
    except rascunho.PropostaInvalida as erro:
        # 502: quem falhou foi o serviço de IA, não o pedido de quem chamou.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(erro)) from None

    return RascunhoResponse(
        pt=resultado.pt,
        justificativa=resultado.justificativa,
        fontes=resultado.fontes,
        pendencias=[pendencia.como_dict() for pendencia in resultado.pendencias],
        tokens_entrada=resultado.tokens_entrada,
        tokens_saida=resultado.tokens_saida,
    )
