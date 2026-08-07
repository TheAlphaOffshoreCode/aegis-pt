"""Consulta em linguagem natural sobre as PTs."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai import agente
from app.database import get_db
from app.models.pessoa import Usuario
from app.schemas.ai import ConsultaRequest, ConsultaResponse
from app.security.dependencias import usuario_atual

router = APIRouter(prefix="/ai", tags=["ia"])


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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Consulta por IA indisponível: chave da Claude API não configurada",
        ) from None

    return ConsultaResponse(
        resposta=resultado.texto,
        fontes=resultado.fontes,
        iteracoes=resultado.iteracoes,
        tokens_entrada=resultado.tokens_entrada,
        tokens_saida=resultado.tokens_saida,
    )
