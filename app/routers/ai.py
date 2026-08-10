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
from app.security.limite import IA, chave_do_pedido

router = APIRouter(prefix="/ai", tags=["ia"])

SEM_MODELO = "Consulta por IA indisponível: {motivo}"


@router.post("/consulta", response_model=ConsultaResponse)
def consulta(
    dados: ConsultaRequest,
    request: Request,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
) -> ConsultaResponse:
    """Responde em linguagem natural, citando as PTs consultadas.

    O escopo de quem pergunta entra nas ferramentas antes da chamada ao modelo, e as fontes
    saem do que o banco devolveu — não do que a resposta afirma ter consultado.
    """
    _limitar(request, usuario)
    try:
        resultado = agente.responder(db, usuario, dados.pergunta)
    except agente.IAIndisponivel as erro:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, SEM_MODELO.format(motivo=erro)
        ) from None

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
    _limitar(request, usuario)
    contexto = Contexto(
        dispositivo=request.headers.get("user-agent"),
        ip=None if request.client is None else request.client.host,
    )
    try:
        resultado = rascunho.propor(db, usuario, dados.model_dump(), contexto=contexto)
    except agente.IAIndisponivel as erro:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, SEM_MODELO.format(motivo=erro)
        ) from None
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


def _limitar(request: Request, usuario: Usuario) -> None:
    """Cada consulta custa tokens, e o rascunho ainda cria PT.

    O limite é por pessoa e origem: um cliente com defeito em laço encheria o acervo de
    rascunhos e a fatura de tokens antes de alguém perceber.
    """
    chave = chave_do_pedido(
        None if request.client is None else request.client.host, str(usuario.id)
    )
    IA.exigir(chave)
    IA.registrar(chave)
