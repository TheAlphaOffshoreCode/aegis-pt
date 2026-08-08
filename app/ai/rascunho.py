"""Proposta de rascunho de PT. A IA escreve o texto; ninguém mais que isso.

Onde exatamente passa a linha, e por quê:

- **A IA propõe** tipo de trabalho, descrição do serviço, perigos e controles. É a parte que
  hoje é copiada da última PT parecida, com os erros junto.
- **A IA não preenche nenhuma resposta do formulário.** Os campos do modelo são medição e
  atestado — `teste_de_gases_lie` sai de um detector calibrado, `altura_metros` de uma trena,
  `area_isolada` de alguém que foi lá olhar. Número de segurança não sai de modelo de
  linguagem (regra 2), e "parece plausível" é exatamente o modo de falhar aqui. As respostas
  chegam prontas no pedido, de quem vai a bordo, e são repassadas sem o modelo nunca vê-las.
- **A janela de validade vem de quem pede**, não do modelo: prazo é número de segurança.
- **O rascunho nasce rascunho.** Passa por `permissoes.criar_pt`, o mesmo caminho de qualquer
  outra PT — mesma validação, mesma numeração, mesma trilha, mesmo fluxo de assinatura.
  Propor não é aprovar (regra 1), e não existe atalho aqui que pule etapa.
"""

from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import agente
from app.audit.trilha import Contexto
from app.models.enums import TipoTrabalho
from app.models.permissao import ModeloPT, PermissaoTrabalho
from app.models.pessoa import Usuario
from app.rules.pendencias import Pendencia
from app.schemas.permissao import PermissaoTrabalhoCreate
from app.services import permissoes

TIPO_EVENTO = "pt.criada_por_ia"

_ITEM = {
    "type": "object",
    "properties": {"descricao": {"type": "string"}},
    "required": ["descricao"],
    "additionalProperties": False,
}

# `additionalProperties: false` em todo objeto é exigência do schema estruturado — e aqui
# serve duas vezes: o modelo não consegue devolver um campo que não pedimos.
ESQUEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "tipo_trabalho": {"type": "string", "enum": [t.value for t in TipoTrabalho]},
            "descricao": {"type": "string"},
            "perigos": {"type": "array", "items": _ITEM},
            "controles": {"type": "array", "items": _ITEM},
            "justificativa": {"type": "string"},
        },
        "required": ["tipo_trabalho", "descricao", "perigos", "controles", "justificativa"],
        "additionalProperties": False,
    },
}

INSTRUCOES = """Você prepara o rascunho de uma permissão de trabalho (PT) de unidade offshore \
a partir da descrição que a pessoa escreveu, para que ela revise e complete.

O que você entrega: o tipo de trabalho, uma descrição objetiva do serviço, a lista de perigos \
e a lista de controles.

O que você NÃO faz, sem exceção:

1. Você não preenche campo de formulário, medição, data nem confirmação. Teste de gases, \
altura, isolamento de área, nome de vigia de fogo e inspeção de equipamento são levantados a \
bordo, por quem vai lá — não por você.
2. Você não aprova, libera nem assina nada. O que você produz é rascunho e será revisado, \
completado e assinado pelas pessoas responsáveis.
3. Você não inventa prazo, distância, carga nem quantidade. Se algum número aparecer na sua \
saída, ele veio literalmente da descrição da pessoa.

Use as ferramentas para consultar PTs semelhantes já emitidas nesta unidade e baseie perigos e \
controles no que a operação de fato usa, em vez de escrever do zero. Se não encontrar nenhuma \
parecida, escreva a partir da descrição mesmo — e diga isso na justificativa.

Escolha o tipo de trabalho que corresponde ao serviço descrito. Na dúvida entre dois, escolha \
o mais restritivo e explique na justificativa.

Perigos e controles: uma frase por item, concreta e verificável a bordo. "Risco de acidente" \
não serve; "projeção de fagulhas sobre o convés inferior" serve.

A justificativa é para quem vai revisar: em duas ou três frases, diga em que você se baseou e \
o que ficou faltando. Escreva tudo em português do Brasil."""


class Proposta(BaseModel):
    """O que o modelo devolveu, já validado. Campo fora deste schema não entra na PT."""

    tipo_trabalho: TipoTrabalho
    descricao: str = Field(min_length=1)
    perigos: list[dict]
    controles: list[dict]
    justificativa: str


@dataclass
class Rascunho:
    pt: PermissaoTrabalho
    justificativa: str
    fontes: list[str] = field(default_factory=list)
    pendencias: list[Pendencia] = field(default_factory=list)
    tokens_entrada: int = 0
    tokens_saida: int = 0


class PropostaInvalida(RuntimeError):
    """O modelo não devolveu uma proposta utilizável."""


def _pedido(descricao_livre: str) -> str:
    return f"Descrição do serviço, escrita por quem vai emitir a PT:\n\n{descricao_livre}"


def propor(
    db: Session,
    usuario: Usuario,
    dados: dict,
    cliente: agente.ClienteClaude | None = None,
    contexto: Contexto = Contexto(),
) -> Rascunho:
    """Propõe um rascunho e o cria — em `RASCUNHO`, pelo caminho normal de criação.

    `dados` traz o que é decisão de gente: unidade, área, equipamento e a janela de validade.
    """
    turno = agente.conversar(
        db,
        usuario,
        INSTRUCOES,
        _pedido(dados["descricao_livre"]),
        cliente or agente.construir_cliente(),
        formato=ESQUEMA,
    )
    if turno.parada == "recusa":
        raise PropostaInvalida("O modelo recusou preparar este rascunho.")
    if turno.parada == "limite":
        raise PropostaInvalida("A proposta não se resolveu no número de passos disponível.")

    try:
        proposta = Proposta.model_validate_json(turno.texto)
    except ValidationError as erro:
        # O schema estruturado já prende o formato; isto pega o resto — inclusive um tipo de
        # trabalho que não existe no domínio.
        raise PropostaInvalida("O modelo devolveu uma proposta fora do formato.") from erro

    modelo = db.scalars(
        select(ModeloPT)
        .where(ModeloPT.tipo_trabalho == proposta.tipo_trabalho, ModeloPT.ativo.is_(True))
        .order_by(ModeloPT.versao.desc())
    ).first()
    if modelo is None:
        raise PropostaInvalida(
            f"Não há modelo de formulário ativo para {proposta.tipo_trabalho.value}."
        )

    pt = permissoes.criar_pt(
        db,
        PermissaoTrabalhoCreate(
            tipo_trabalho=proposta.tipo_trabalho,
            modelo_pt_id=modelo.id,
            unidade_id=dados["unidade_id"],
            area_id=dados["area_id"],
            equipamento_id=dados.get("equipamento_id"),
            descricao=proposta.descricao,
            valida_de=dados["valida_de"],
            valida_ate=dados["valida_ate"],
            perigos=proposta.perigos,
            controles=proposta.controles,
            # Vêm do pedido, intactas: o modelo nunca as viu nem as escreveu (regra 2).
            respostas=dados.get("respostas") or {},
        ),
        autor=usuario,
        contexto=contexto,
        tipo_evento=TIPO_EVENTO,
    )

    return Rascunho(
        pt=pt,
        justificativa=proposta.justificativa,
        fontes=turno.fontes,
        # O que falta vem do motor de regras, não de uma lista que a IA escreveu — é o mesmo
        # veredito que vai barrar a liberação depois.
        pendencias=permissoes.pendencias_da_pt(db, pt),
        tokens_entrada=turno.tokens_entrada,
        tokens_saida=turno.tokens_saida,
    )
