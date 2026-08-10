"""Modelo local: tradução de formato nos dois sentidos, e as garantias que não mudam.

Nada aqui sai para a rede nem exige Ollama instalado — o cliente fala com um transporte de
mentira. O que se prova é que o laço do L9 não sabe a diferença, e que as regras continuam
valendo quando quem responde é um modelo de 8B em vez do Opus.
"""

import json
from collections.abc import Callable

import httpx
import pytest
from sqlalchemy.orm import Session

from app.ai import agente, ferramentas
from app.ai.local import ClienteLocal
from app.models.pessoa import Usuario


def servidor(*respostas: dict) -> tuple[ClienteLocal, list[dict]]:
    """Um Ollama de mentira que devolve `respostas` em ordem e guarda o que recebeu."""
    recebidas: list[dict] = []

    def responder(request: httpx.Request) -> httpx.Response:
        recebidas.append(json.loads(request.content))
        corpo = respostas[min(len(recebidas) - 1, len(respostas) - 1)]
        return httpx.Response(200, json=corpo)

    cliente = ClienteLocal(
        "http://local:11434",
        "gemma4:latest",
        contexto=16384,
        timeout=30,
        transporte=httpx.MockTransport(responder),
    )
    return cliente, recebidas


def fala(texto: str) -> dict:
    return {"message": {"content": texto}, "prompt_eval_count": 150, "eval_count": 19}


def pede(nome: str, argumentos: dict | str) -> dict:
    return {
        "message": {
            "content": "",
            "tool_calls": [{"function": {"name": nome, "arguments": argumentos}}],
        },
        "prompt_eval_count": 150,
        "eval_count": 19,
    }


@pytest.fixture
def usuario(criar_usuario: Callable[..., Usuario]) -> Usuario:
    return criar_usuario(matricula="80001")


# --- tradução de ida ----------------------------------------------------------------------


def test_ferramentas_saem_no_envelope_do_ollama(db: Session, usuario: Usuario) -> None:
    """`input_schema` da Anthropic vira `function.parameters`, com os nomes intactos."""
    cliente, recebidas = servidor(fala("..."))

    agente.responder(db, usuario, "Quais PTs?", cliente)

    enviadas = recebidas[0]["tools"]
    assert {f["function"]["name"] for f in enviadas} == ferramentas.NOMES
    assert all(f["type"] == "function" for f in enviadas)
    primeira = next(f for f in enviadas if f["function"]["name"] == "buscar_pts")
    assert primeira["function"]["parameters"]["type"] == "object"
    assert "estado" in primeira["function"]["parameters"]["properties"]


def test_janela_de_contexto_vai_explicita(db: Session, usuario: Usuario) -> None:
    """O corte do Ollama é silencioso e come o system — onde vivem as regras invioláveis."""
    cliente, recebidas = servidor(fala("..."))

    agente.responder(db, usuario, "Quais PTs?", cliente)

    assert recebidas[0]["options"]["num_ctx"] == 16384
    assert recebidas[0]["messages"][0]["role"] == "system"


def test_raciocinio_vai_ligado_por_padrao(db: Session, usuario: Usuario) -> None:
    """É o que faz o modelo local chamar ferramenta; desligado, ele conversa e não consulta."""
    cliente, recebidas = servidor(fala("..."))

    agente.responder(db, usuario, "Quais PTs?", cliente)

    assert recebidas[0]["think"] is True


def test_schema_estruturado_perde_o_envelope(db: Session, usuario: Usuario) -> None:
    """A Anthropic embrulha em `{type, schema}`; o Ollama quer o schema cru."""
    cliente, recebidas = servidor(fala("{}"))
    esquema = {"type": "object", "properties": {"a": {"type": "string"}}}

    agente.conversar(
        db, usuario, "sistema", "pedido", cliente,
        formato={"type": "json_schema", "schema": esquema},
    )

    assert recebidas[0]["format"] == esquema


# --- tradução de volta --------------------------------------------------------------------


def test_pedido_de_ferramenta_vira_bloco_de_uso(db: Session, usuario: Usuario) -> None:
    cliente, _ = servidor(pede("buscar_pts", {"estado": "EM_EXECUCAO"}))

    resposta = cliente.messages.create(
        model="x", max_tokens=100, output_config={}, system="s",
        tools=ferramentas.DEFINICOES, messages=[{"role": "user", "content": "oi"}],
    )

    assert resposta.stop_reason == "tool_use"
    bloco = resposta.content[0]
    assert (bloco.type, bloco.name, bloco.input) == ("tool_use", "buscar_pts", {"estado": "EM_EXECUCAO"})
    assert (resposta.usage.input_tokens, resposta.usage.output_tokens) == (150, 19)


def test_argumentos_em_texto_tambem_sao_lidos(db: Session, usuario: Usuario) -> None:
    """Versões do Ollama divergem: umas mandam objeto, outras a string JSON."""
    cliente, _ = servidor(pede("buscar_pts", '{"estado": "RASCUNHO"}'))

    resposta = cliente.messages.create(
        model="x", max_tokens=100, output_config={}, system="s",
        tools=ferramentas.DEFINICOES, messages=[{"role": "user", "content": "oi"}],
    )

    assert resposta.content[0].input == {"estado": "RASCUNHO"}


def test_o_laco_completo_devolve_o_resultado_como_mensagem_tool(
    db: Session, usuario: Usuario
) -> None:
    """A volta é o passo que mais tem como quebrar: o Ollama quer o *nome* da ferramenta.

    A Claude API devolve um `tool_use_id` opaco; aqui o nome viaja dentro do id e volta no
    campo `tool_name`, ou o modelo recebe um resultado que não sabe de quem é.
    """
    cliente, recebidas = servidor(
        pede("buscar_pts", {"estado": "RASCUNHO"}),
        fala("Nenhuma PT encontrada."),
    )

    agente.responder(db, usuario, "Quais PTs em rascunho?", cliente)

    assert len(recebidas) == 2
    historico = recebidas[1]["messages"]
    assistente = next(m for m in historico if m["role"] == "assistant")
    assert assistente["tool_calls"][0]["function"]["name"] == "buscar_pts"
    resultado = next(m for m in historico if m["role"] == "tool")
    assert resultado["tool_name"] == "buscar_pts"
    assert json.loads(resultado["content"])["total"] == 0


# --- as garantias não mudam de dono -------------------------------------------------------


def test_resposta_sem_fonte_e_descartada_tambem_no_local(db: Session, usuario: Usuario) -> None:
    """Regra 3 com um modelo fraco: PT inventada não vira resposta.

    É o caso que mais importa aqui — um 8B alucina número de PT com muito mais facilidade que
    o Opus, e a contenção não é o prompt: é `_com_fontes` jogando fora um texto que o banco
    não sustenta.
    """
    cliente, _ = servidor(fala("A PT-2026-0099 está liberada e pode iniciar."))

    resultado = agente.responder(db, usuario, "Qual PT está liberada?", cliente)

    assert resultado.texto == agente.SEM_FONTE
    assert resultado.fontes == []


def test_servidor_local_fora_do_ar_vira_indisponivel(db: Session, usuario: Usuario) -> None:
    """Mesma porta de saída da chave ausente: 503, e o resto da aplicação de pé."""

    def recusar(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conexão recusada")

    cliente = ClienteLocal(
        "http://local:11434", "gemma4:latest", contexto=16384, timeout=30,
        transporte=httpx.MockTransport(recusar),
    )

    with pytest.raises(agente.IAIndisponivel, match="não respondeu"):
        agente.responder(db, usuario, "Quais PTs?", cliente)


def test_erro_do_servidor_local_diz_que_foi_erro(db: Session, usuario: Usuario) -> None:
    """As duas causas não podem ter a mesma mensagem.

    Servidor no ar devolvendo 500 (o runner morre ao carregar o modelo) e servidor fora do ar
    pedem investigações opostas. Confundir as duas custou meia hora de diagnóstico de verdade.
    """
    cliente = ClienteLocal(
        "http://local:11434", "gemma4:latest", contexto=16384, timeout=30,
        transporte=httpx.MockTransport(
            lambda r: httpx.Response(500, json={"error": "llama-server has terminated"})
        ),
    )

    with pytest.raises(agente.IAIndisponivel, match="respondeu HTTP 500"):
        agente.responder(db, usuario, "Quais PTs?", cliente)


def test_camadas_de_gpu_so_vao_quando_fixadas(db: Session, usuario: Usuario) -> None:
    """Fixar sem necessidade seria pior que não fixar: o Ollama decide melhor num servidor."""
    cliente, recebidas = servidor(fala("..."))
    agente.responder(db, usuario, "Quais PTs?", cliente)
    assert "num_gpu" not in recebidas[0]["options"]

    fixado, recebidas_fixadas = servidor(fala("..."))
    fixado.num_gpu = 10
    agente.responder(db, usuario, "Quais PTs?", fixado)
    assert recebidas_fixadas[0]["options"]["num_gpu"] == 10
