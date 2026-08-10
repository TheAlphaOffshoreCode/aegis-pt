"""Cliente de um modelo local servido por Ollama, no formato que o laço já fala.

Existe por uma razão de operação, não de custo: numa unidade offshore o enlace é caro,
intermitente e às vezes ausente, e o conteúdo de uma PT é dado operacional que não precisa
sair de bordo. Um modelo rodando no servidor da unidade responde sem enlace e sem chave.

**Trocar o modelo aqui não afeta nenhuma das oito regras**, e isso é consequência de elas
serem estruturais: nenhuma ferramenta escreve (regra 1), número de segurança vem de
`app/rules/` (regra 2), a fonte é colhida do que o banco devolveu e não do texto da resposta
(regra 3), e o escopo entra na consulta antes da chamada (regra 5). Um modelo mais fraco
responde pior — não responde com mais poder. A regra 7 simplesmente deixa de existir: não há
chave nenhuma.

O que este módulo faz é só tradução de formato, nos dois sentidos. `agente.conversar()` não
sabe que existe um modelo local, e não deve saber.
"""

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx

from app.ai.agente import IAIndisponivel

# Separa o nome da ferramenta do índice dentro do turno. A Claude API devolve um
# `tool_use_id` opaco e o Ollama quer o *nome* da ferramenta de volta na resposta; guardar o
# nome dentro do id é o que permite traduzir sem carregar um mapa entre as duas chamadas.
SEPARADOR = "#"


@dataclass
class BlocoTexto:
    text: str
    type: str = "text"


@dataclass
class BlocoFerramenta:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class Uso:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class RespostaLocal:
    stop_reason: str
    content: list[Any] = field(default_factory=list)
    usage: Uso = field(default_factory=Uso)


def _ferramentas(definicoes: list[dict]) -> list[dict]:
    """`{name, description, input_schema}` da Anthropic vira o envelope de função do Ollama."""
    return [
        {
            "type": "function",
            "function": {
                "name": d["name"],
                "description": d["description"],
                "parameters": d["input_schema"],
            },
        }
        for d in definicoes
    ]


def _mensagens(mensagens: list[dict]) -> list[dict]:
    """Histórico no formato da Anthropic vira o do Ollama.

    Três formas aparecem: texto puro, o turno do assistente que pediu ferramentas (blocos
    desta casa, devolvidos intactos pelo laço) e os resultados das ferramentas.
    """
    saida: list[dict] = []
    for mensagem in mensagens:
        conteudo = mensagem["content"]

        if isinstance(conteudo, str):
            saida.append({"role": mensagem["role"], "content": conteudo})
            continue

        # Resultados de ferramenta: no Ollama cada um é uma mensagem `tool` própria, e não
        # um turno de usuário com vários blocos dentro.
        # `conteudo and` porque `all()` de lista vazia é verdadeiro, e um turno sem bloco
        # nenhum sairia como zero mensagens em vez de um assistente mudo.
        if conteudo and all(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in conteudo
        ):
            for bloco in conteudo:
                saida.append(
                    {
                        "role": "tool",
                        "tool_name": str(bloco["tool_use_id"]).split(SEPARADOR)[0],
                        "content": bloco["content"],
                    }
                )
            continue

        texto = "".join(b.text for b in conteudo if b.type == "text")
        chamadas = [
            {"function": {"name": b.name, "arguments": b.input}}
            for b in conteudo
            if b.type == "tool_use"
        ]
        turno: dict[str, Any] = {"role": "assistant", "content": texto}
        if chamadas:
            turno["tool_calls"] = chamadas
        saida.append(turno)
    return saida


def _argumentos(bruto: Any) -> dict:
    """O Ollama devolve os argumentos já como objeto, mas nem sempre — versões variam."""
    if isinstance(bruto, str):
        try:
            return json.loads(bruto)
        except json.JSONDecodeError:
            return {}
    return bruto or {}


def _resposta(corpo: dict) -> RespostaLocal:
    """A resposta do Ollama vira o formato que o laço lê.

    Não existe `refusal`: um modelo local não tem classificador na frente. O laço já trata
    isso — `parada` só vira `recusa` se o campo vier, e daqui ele nunca vem.
    """
    mensagem = corpo.get("message") or {}
    uso = Uso(
        input_tokens=corpo.get("prompt_eval_count") or 0,
        output_tokens=corpo.get("eval_count") or 0,
    )

    blocos: list[Any] = []
    if mensagem.get("content"):
        blocos.append(BlocoTexto(text=mensagem["content"]))

    chamadas = mensagem.get("tool_calls") or []
    for indice, chamada in enumerate(chamadas):
        funcao = chamada.get("function") or {}
        nome = funcao.get("name", "")
        blocos.append(
            BlocoFerramenta(
                id=f"{nome}{SEPARADOR}{indice}",
                name=nome,
                input=_argumentos(funcao.get("arguments")),
            )
        )

    return RespostaLocal("tool_use" if chamadas else "end_turn", blocos, uso)


class ClienteLocal:
    """Fala com o Ollama e devolve o que `agente.conversar()` espera."""

    def __init__(
        self,
        base_url: str,
        modelo: str,
        contexto: int,
        timeout: int,
        num_gpu: int | None = None,
        pensar: bool = True,
        transporte: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.modelo = modelo
        self.contexto = contexto
        self.timeout = timeout
        self.num_gpu = num_gpu
        self.pensar = pensar
        # `transporte` existe para o teste falar com um servidor de mentira sem subir nada.
        self._transporte = transporte
        # É tudo o que o laço usa do cliente: `cliente.messages.create(...)`.
        self.messages = SimpleNamespace(create=self.responder)

    def responder(
        self,
        *,
        model: str,
        max_tokens: int,
        output_config: dict,
        system: str,
        tools: list[dict],
        messages: list[dict],
    ) -> RespostaLocal:
        """Uma ida ao modelo local. `model` vem do laço e é ignorado: quem manda é o cliente.

        `output_config.effort` não tem equivalente e é descartado — o esforço de um modelo
        local é decidido por quem escolheu o modelo e o hardware, não por parâmetro.
        """
        corpo: dict[str, Any] = {
            "model": self.modelo,
            "stream": False,
            # Medido, não suposto: sem raciocínio o gemma4 devolve uma pergunta de volta em
            # vez de chamar a ferramenta, e a resposta acaba descartada por não ter fonte.
            "think": self.pensar,
            "tools": _ferramentas(tools),
            "messages": [{"role": "system", "content": system}] + _mensagens(messages),
            "options": {
                "num_predict": max_tokens,
                # Explícito de propósito: o padrão do Ollama é bem menor que a janela do
                # modelo, e o corte é **silencioso** e pela frente da conversa — ou seja,
                # come justamente o system, que é onde vivem as regras. Um schema de
                # ferramenta mais um dossiê de PT passam desse padrão com folga.
                "num_ctx": self.contexto,
            },
        }
        if self.num_gpu is not None:
            # Só quando fixado: o padrão do Ollama é decidir sozinho, e num servidor com placa
            # que caiba o modelo essa é a escolha certa.
            corpo["options"]["num_gpu"] = self.num_gpu

        formato = (output_config or {}).get("format")
        if formato:
            # A Anthropic embrulha em `{"type": "json_schema", "schema": ...}`; o Ollama quer
            # o schema cru.
            corpo["format"] = formato.get("schema", formato)

        # Mesma porta de saída da chave ausente: a IA cai sozinha, com 503, e o resto da
        # aplicação continua de pé. Servidor local fora não é erro de quem chamou.
        #
        # As duas causas ficam separadas de propósito. Tratá-las como uma só custou meia hora
        # de diagnóstico aqui: o servidor estava no ar e devolvendo 500 (o runner morria ao
        # carregar o modelo), e a mensagem dizia "indisponível", mandando procurar no lugar
        # errado. O corpo do erro fica de fora — quem lê o 503 está a bordo, não no console.
        try:
            # Cliente por chamada, fechado no fim: `construir_cliente()` roda a cada
            # requisição, e um pool que fica para o coletor vaza soquete num processo que não
            # reinicia. A rota é limitada a 20/min — não é caminho quente.
            with httpx.Client(
                base_url=self.base_url, timeout=self.timeout, transport=self._transporte
            ) as http:
                resposta = http.post("/api/chat", json=corpo)
        except httpx.HTTPError as erro:
            raise IAIndisponivel(f"modelo local não respondeu em {self.base_url}") from erro

        if resposta.status_code != httpx.codes.OK:
            raise IAIndisponivel(
                f"modelo local {self.modelo} respondeu HTTP {resposta.status_code}"
            )

        return _resposta(resposta.json())
