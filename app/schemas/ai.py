"""Schemas da consulta em linguagem natural."""

from pydantic import BaseModel, Field


class ConsultaRequest(BaseModel):
    pergunta: str = Field(min_length=3, max_length=1000)


class ConsultaResponse(BaseModel):
    """Resposta e as PTs que a embasam.

    `fontes` são as PTs que as ferramentas efetivamente leram — não as que o texto menciona.
    Lista vazia significa que nada foi recuperado, e então a resposta é "não encontrei".
    """

    resposta: str
    fontes: list[str]
    iteracoes: int
    tokens_entrada: int
    tokens_saida: int
