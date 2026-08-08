"""Schemas da consulta em linguagem natural e da proposta de rascunho."""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.permissao import PermissaoTrabalhoRead


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


class RascunhoRequest(BaseModel):
    """O pedido de rascunho — e a divisão de trabalho, escrita no contrato.

    Tudo que é medição ou prazo entra por aqui, de gente: a janela de validade, a unidade, a
    área e as `respostas` do formulário. Número de segurança não sai de modelo de linguagem
    (regra 2), e teste de gases se lê num detector, não se redige.

    A IA devolve o resto: tipo de trabalho, descrição, perigos e controles.

    Como o tipo é escolhido pela IA, as `respostas` enviadas podem não corresponder ao
    formulário do tipo escolhido — nesse caso a criação responde `409` com a lista exata de
    campos que faltam, e `GET /pts/modelos/{tipo}` diz quais são.
    """

    descricao_livre: str = Field(min_length=10, max_length=2000)
    unidade_id: int
    area_id: int
    equipamento_id: int | None = None
    valida_de: datetime
    valida_ate: datetime
    respostas: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _janela_valida(self) -> "RascunhoRequest":
        if self.valida_ate <= self.valida_de:
            raise ValueError("valida_ate precisa ser posterior a valida_de")
        return self


class RascunhoResponse(BaseModel):
    """A PT criada em rascunho, mais o que ainda depende de gente.

    `pendencias` é o veredito do motor de regras, não uma lista que a IA escreveu — é o mesmo
    que vai barrar a liberação enquanto o formulário não for preenchido a bordo.
    """

    pt: PermissaoTrabalhoRead
    justificativa: str
    fontes: list[str]
    pendencias: list[dict]
    tokens_entrada: int
    tokens_saida: int
