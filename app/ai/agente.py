"""Laço de tool-calling contra a Claude API.

Laço manual, e não o tool runner do SDK, por três razões concretas: o escopo do usuário
precisa entrar nas ferramentas antes de qualquer chamada (regra 5); as fontes são colhidas a
cada passo, do que o banco devolveu; e assim a suíte roda sem rede nem chave, injetando um
cliente falso. O tool runner faria o laço por nós, mas escondendo justamente os dois pontos
que aqui são a garantia.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.ai import ferramentas
from app.config import get_settings
from app.models.pessoa import Usuario

SEM_FONTE = (
    "Não encontrei nenhuma permissão de trabalho que responda a essa pergunta dentro do seu "
    "acesso."
)

INSTRUCOES = """Você responde perguntas sobre permissões de trabalho (PT) de uma unidade \
offshore, usando apenas as ferramentas disponíveis.

Regras que não admitem exceção:

1. Você não aprova, libera, encerra nem altera nada. Você lê e responde. Se pedirem uma ação, \
explique que ela é feita no sistema, pela pessoa responsável, e não por você.
2. Nenhum número de segurança sai de você. Prazos, validades, contagens e vereditos vêm das \
ferramentas já calculados — repita-os exatamente como vieram. Não some datas, não estime, não \
converta unidades e não deduza se algo está vencido: pergunte à ferramenta.
3. Cite as PTs que embasam a resposta, sempre pelo número (ex.: PT-2026-0002). Se as \
ferramentas não devolverem nenhuma PT, responda que não encontrou — nunca preencha a lacuna \
com o que parece plausível.
4. Se as ferramentas devolverem menos do que a pergunta pede, diga o que faltou em vez de \
completar por conta própria.

Responda em português do Brasil, de forma direta e curta. Uma pessoa a bordo lê isso com o \
rádio na outra mão."""


class ClienteClaude(Protocol):
    """O que o agente precisa de um cliente — o suficiente para injetar um falso no teste."""

    @property
    def messages(self) -> Any: ...


@dataclass
class Turno:
    """O que sobrou de uma conversa inteira com o modelo.

    `parada` diz por que ela terminou: `ok` chegou ao fim, `recusa` foi barrada pelos
    classificadores, `limite` gastou as iterações sem concluir.
    """

    texto: str
    fontes: list[str] = field(default_factory=list)
    iteracoes: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    parada: str = "ok"


@dataclass
class Resposta:
    texto: str
    fontes: list[str] = field(default_factory=list)
    iteracoes: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0


class IAIndisponivel(RuntimeError):
    """Chave da Claude API não configurada."""


def construir_cliente() -> ClienteClaude:
    """Cliente real. A chave é lida aqui, no backend, e nunca sai daqui (regra 7)."""
    chave = get_settings().anthropic_api_key
    if not chave:
        raise IAIndisponivel("AEGIS_ANTHROPIC_API_KEY não configurada")
    import anthropic

    return anthropic.Anthropic(api_key=chave)


def conversar(
    db: Session,
    usuario: Usuario,
    sistema: str,
    pedido: str,
    cliente: ClienteClaude,
    formato: dict | None = None,
) -> Turno:
    """Roda a conversa até o modelo parar de pedir ferramentas.

    Compartilhado pela consulta (L9) e pela proposta de rascunho (L10): as duas precisam do
    mesmo escopo aplicado antes da chamada e da mesma coleta de fontes. `formato` prende a
    resposta final a um schema JSON — as ferramentas continuam funcionando no meio do caminho.
    """
    configuracao = get_settings()
    saida_config: dict = {"effort": configuracao.ai_esforco}
    if formato is not None:
        saida_config["format"] = formato

    mensagens: list[dict] = [{"role": "user", "content": pedido}]
    fontes: list[str] = []
    entrada = saida = 0

    for iteracao in range(1, configuracao.ai_max_iteracoes + 1):
        resposta = cliente.messages.create(
            model=configuracao.ai_modelo,
            # Folga porque o raciocínio adaptativo do Opus 5 divide este teto com a resposta.
            max_tokens=configuracao.ai_max_tokens,
            output_config=saida_config,
            system=sistema,
            tools=ferramentas.DEFINICOES,
            messages=mensagens,
        )
        uso = getattr(resposta, "usage", None)
        entrada += getattr(uso, "input_tokens", 0) or 0
        saida += getattr(uso, "output_tokens", 0) or 0

        # Conferido antes de ler `content`: numa recusa o conteúdo vem vazio ou parcial.
        if resposta.stop_reason == "refusal":
            return Turno("", fontes, iteracao, entrada, saida, parada="recusa")

        if resposta.stop_reason != "tool_use":
            texto = "".join(b.text for b in resposta.content if b.type == "text").strip()
            return Turno(texto, fontes, iteracao, entrada, saida)

        # O turno inteiro volta para o histórico, blocos de raciocínio inclusive: editar o
        # conteúdo do assistente quebra a continuidade da conversa.
        mensagens.append({"role": "assistant", "content": resposta.content})

        resultados = []
        for bloco in resposta.content:
            if bloco.type != "tool_use":
                continue
            conteudo, alcancadas = ferramentas.executar(bloco.name, bloco.input, db, usuario)
            fontes.extend(n for n in alcancadas if n not in fontes)
            resultados.append(
                {"type": "tool_result", "tool_use_id": bloco.id, "content": conteudo}
            )
        # Todos os resultados num único turno: dividi-los ensina o modelo a parar de pedir
        # ferramentas em paralelo.
        mensagens.append({"role": "user", "content": resultados})

    return Turno("", fontes, configuracao.ai_max_iteracoes, entrada, saida, parada="limite")


def responder(
    db: Session, usuario: Usuario, pergunta: str, cliente: ClienteClaude | None = None
) -> Resposta:
    """Responde uma pergunta em linguagem natural sobre as PTs que o usuário alcança."""
    turno = conversar(db, usuario, INSTRUCOES, pergunta, cliente or construir_cliente())

    if turno.parada == "recusa":
        return Resposta(
            "Não posso responder a essa pergunta.",
            [],
            turno.iteracoes,
            turno.tokens_entrada,
            turno.tokens_saida,
        )
    if turno.parada == "limite":
        return _com_fontes(
            "A consulta não se resolveu no número de passos disponível. Refaça a pergunta de "
            "forma mais específica.",
            turno.fontes,
            turno.iteracoes,
            turno.tokens_entrada,
            turno.tokens_saida,
        )
    return _com_fontes(
        turno.texto, turno.fontes, turno.iteracoes, turno.tokens_entrada, turno.tokens_saida
    )


def _com_fontes(
    texto: str, fontes: list[str], iteracoes: int, entrada: int, saida: int
) -> Resposta:
    """Sem documento recuperado, a resposta é 'não encontrei' — decidido aqui, não pelo modelo.

    A regra 3 não pode depender de o modelo lembrar de citar: as fontes são as PTs que as
    ferramentas de fato leram, e um texto sem nenhuma delas é descartado inteiro.
    """
    if not fontes:
        return Resposta(SEM_FONTE, [], iteracoes, entrada, saida)
    return Resposta(texto or SEM_FONTE, fontes, iteracoes, entrada, saida)
