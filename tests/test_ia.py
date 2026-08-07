"""Consulta por IA: escopo, somente-leitura e citação obrigatória.

Nenhum teste aqui sai para a rede. O agente recebe um cliente falso que devolve turnos
roteirizados, e a suíte roda sem chave da Claude API — inclusive na CI.
"""

from collections.abc import Callable
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import agente, ferramentas
from app.models import Area, AuditEvent, ModeloPT, PermissaoTrabalho, Unidade, Usuario
from app.models.enums import PerfilUsuario, TipoTrabalho, TipoUnidade
from app.models.tipos import agora_utc


def texto(conteudo: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=conteudo)


def uso_de_ferramenta(nome: str, entrada: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=f"tu_{nome}", name=nome, input=entrada)


class ClienteFalso:
    """Devolve turnos roteirizados e guarda o que foi enviado, para inspeção."""

    def __init__(self, *turnos: SimpleNamespace) -> None:
        self.turnos = list(turnos)
        self.chamadas: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs) -> SimpleNamespace:
        self.chamadas.append(kwargs)
        # O último turno se repete: assim um roteiro de um passo cobre o laço inteiro.
        return self.turnos[min(len(self.chamadas) - 1, len(self.turnos) - 1)]


def turno(*blocos: SimpleNamespace, parada: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=parada,
        content=list(blocos),
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )


@pytest.fixture
def cenario(
    client: TestClient, db: Session,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> dict:
    """Uma PT na unidade Alfa, um usuário de Alfa e um usuário de Beta."""
    alfa = Unidade(nome="FPSO Alfa", identificador_operacional="FPSO-A", tipo=TipoUnidade.FPSO)
    beta = Unidade(nome="FPSO Beta", identificador_operacional="FPSO-B", tipo=TipoUnidade.FPSO)
    db.add_all([alfa, beta])
    db.flush()
    area = Area(unidade_id=alfa.id, nome="Convés", codigo="CV")
    modelo = ModeloPT(tipo_trabalho=TipoTrabalho.TRABALHO_A_QUENTE, nome="quente", campos=[])
    db.add_all([area, modelo])
    db.commit()

    de_alfa = criar_usuario(matricula="70001", unidade_id=alfa.id)
    de_beta = criar_usuario(matricula="70002", unidade_id=beta.id)
    cabecalho = autenticar("70001")
    inicio = agora_utc()

    resposta = client.post(
        "/pts",
        headers=cabecalho,
        json={
            "tipo_trabalho": TipoTrabalho.TRABALHO_A_QUENTE.value,
            "modelo_pt_id": modelo.id,
            "unidade_id": alfa.id,
            "area_id": area.id,
            "descricao": "Solda em suporte de tubulação",
            "valida_de": inicio.isoformat(),
            "valida_ate": (inicio + timedelta(hours=8)).isoformat(),
        },
    )
    assert resposta.status_code == 201, resposta.text
    db.expire_all()

    return {
        "cabecalho": cabecalho,
        "de_alfa": de_alfa,
        "de_beta": de_beta,
        "numero": resposta.json()["numero"],
    }


# --- regra 1: nenhuma ferramenta escreve -------------------------------------------------


def test_o_conjunto_de_ferramentas_e_fechado() -> None:
    """Tripwire da regra 1: ferramenta nova quebra este teste de propósito.

    Não é para atualizar o conjunto sem antes provar que a nova ferramenta só lê — não existe
    caminho técnico pelo qual o modelo aprove, libere ou encerre uma PT.
    """
    assert ferramentas.NOMES == {"buscar_pts", "detalhar_pt", "pendencias_da_pt"}


def test_ferramentas_nao_alteram_nada(db: Session, cenario: dict) -> None:
    def contagens() -> tuple:
        pt = db.scalars(select(PermissaoTrabalho)).one()
        return (
            db.scalar(select(func.count()).select_from(PermissaoTrabalho)),
            db.scalar(select(func.count()).select_from(AuditEvent)),
            pt.versao,
            str(pt.estado),
            pt.atualizado_em,
        )

    antes = contagens()
    for nome in ferramentas.NOMES:
        ferramentas.executar(nome, {"numero": cenario["numero"]}, db, cenario["de_alfa"])
    db.expire_all()

    assert contagens() == antes


# --- regra 5: escopo aplicado antes de o modelo ver o dado -------------------------------


def test_busca_de_outra_unidade_nao_alcanca_a_pt(db: Session, cenario: dict) -> None:
    corpo, fontes = ferramentas.executar("buscar_pts", {}, db, cenario["de_beta"])

    assert '"total": 0' in corpo
    assert fontes == []


def test_detalhar_fora_do_escopo_responde_como_inexistente(
    db: Session, cenario: dict
) -> None:
    """Fora do escopo e inexistente dão a mesma resposta — distinguir já seria um vazamento."""
    corpo, fontes = ferramentas.executar(
        "detalhar_pt", {"numero": cenario["numero"]}, db, cenario["de_beta"]
    )

    assert corpo == ferramentas.executar(
        "detalhar_pt", {"numero": "PT-1900-9999"}, db, cenario["de_beta"]
    )[0]
    assert fontes == []


def test_escopo_do_auditor_alcanca_as_duas_unidades(
    db: Session, cenario: dict, criar_usuario: Callable[..., Usuario]
) -> None:
    auditor = criar_usuario(matricula="70003", perfil=PerfilUsuario.AUDITOR)

    _, fontes = ferramentas.executar("buscar_pts", {}, db, auditor)

    assert fontes == [cenario["numero"]]


# --- regra 3: sem fonte, "não encontrei" -------------------------------------------------


def test_resposta_sem_ferramenta_nenhuma_vira_nao_encontrei(
    db: Session, cenario: dict
) -> None:
    """O modelo respondeu de cabeça, sem consultar nada. O código descarta o texto inteiro."""
    cliente = ClienteFalso(turno(texto(f"A {cenario['numero']} está liberada e sem pendências.")))

    resultado = agente.responder(db, cenario["de_alfa"], "A PT está liberada?", cliente)

    assert resultado.texto == agente.SEM_FONTE
    assert resultado.fontes == []


def test_busca_vazia_tambem_vira_nao_encontrei(db: Session, cenario: dict) -> None:
    cliente = ClienteFalso(
        turno(uso_de_ferramenta("buscar_pts", {"texto": "andaime"}), parada="tool_use"),
        turno(texto("Provavelmente existe alguma PT de andaime aberta.")),
    )

    resultado = agente.responder(db, cenario["de_alfa"], "Tem PT de andaime?", cliente)

    assert resultado.texto == agente.SEM_FONTE
    assert resultado.fontes == []


def test_fontes_saem_do_banco_e_nao_do_texto(db: Session, cenario: dict) -> None:
    """O texto cita uma PT que nunca foi lida; as fontes trazem só a que o banco devolveu."""
    cliente = ClienteFalso(
        turno(uso_de_ferramenta("buscar_pts", {}), parada="tool_use"),
        turno(texto("Há uma PT aberta, conforme PT-1900-9999.")),
    )

    resultado = agente.responder(db, cenario["de_alfa"], "Quantas PTs estão abertas?", cliente)

    assert resultado.fontes == [cenario["numero"]]
    assert "PT-1900-9999" not in resultado.fontes


def test_pergunta_de_um_usuario_nao_alcanca_a_pt_do_outro(db: Session, cenario: dict) -> None:
    """O mesmo roteiro, outro usuário: o escopo entra antes da chamada, não depois."""
    roteiro = (
        turno(uso_de_ferramenta("buscar_pts", {}), parada="tool_use"),
        turno(texto("Encontrei uma PT.")),
    )

    de_alfa = agente.responder(db, cenario["de_alfa"], "Quais PTs?", ClienteFalso(*roteiro))
    de_beta = agente.responder(db, cenario["de_beta"], "Quais PTs?", ClienteFalso(*roteiro))

    assert de_alfa.fontes == [cenario["numero"]]
    assert de_beta.texto == agente.SEM_FONTE


# --- laço ---------------------------------------------------------------------------------


def test_varias_ferramentas_no_mesmo_turno_voltam_juntas(db: Session, cenario: dict) -> None:
    numero = cenario["numero"]
    cliente = ClienteFalso(
        turno(
            uso_de_ferramenta("detalhar_pt", {"numero": numero}),
            uso_de_ferramenta("pendencias_da_pt", {"numero": numero}),
            parada="tool_use",
        ),
        turno(texto(f"A {numero} está em rascunho.")),
    )

    resultado = agente.responder(db, cenario["de_alfa"], f"Como está a {numero}?", cliente)

    resultados = cliente.chamadas[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in resultados] == ["tu_detalhar_pt", "tu_pendencias_da_pt"]
    assert resultado.fontes == [numero]
    assert resultado.iteracoes == 2


def test_laco_para_no_limite_de_iteracoes(db: Session, cenario: dict) -> None:
    """Modelo que só pede ferramenta não roda para sempre."""
    cliente = ClienteFalso(turno(uso_de_ferramenta("buscar_pts", {}), parada="tool_use"))

    resultado = agente.responder(db, cenario["de_alfa"], "Quais PTs?", cliente)

    assert len(cliente.chamadas) == 6
    assert resultado.iteracoes == 6
    assert "não se resolveu" in resultado.texto


def test_recusa_encerra_sem_ler_o_conteudo(db: Session, cenario: dict) -> None:
    cliente = ClienteFalso(turno(parada="refusal"))

    resultado = agente.responder(db, cenario["de_alfa"], "Pergunta qualquer", cliente)

    assert resultado.texto == "Não posso responder a essa pergunta."
    assert resultado.fontes == []


def test_ferramenta_inventada_nao_derruba_o_laco(db: Session, cenario: dict) -> None:
    cliente = ClienteFalso(
        turno(uso_de_ferramenta("aprovar_pt", {"numero": cenario["numero"]}), parada="tool_use"),
        turno(texto("Não consigo aprovar PTs.")),
    )

    resultado = agente.responder(db, cenario["de_alfa"], "Aprova a PT", cliente)

    assert resultado.texto == agente.SEM_FONTE
    assert "desconhecida" in cliente.chamadas[1]["messages"][-1]["content"][0]["content"]


def test_requisicao_nao_manda_temperatura(db: Session, cenario: dict) -> None:
    """`temperature`, `top_p` e `top_k` são rejeitados com 400 no Opus 5."""
    cliente = ClienteFalso(turno(texto("...")))

    agente.responder(db, cenario["de_alfa"], "Pergunta", cliente)

    enviado = cliente.chamadas[0]
    assert {"temperature", "top_p", "top_k"}.isdisjoint(enviado)
    assert enviado["model"] == "claude-opus-5"
    assert enviado["output_config"] == {"effort": "medium"}


# --- endpoint -----------------------------------------------------------------------------


def test_consulta_exige_autenticacao(client: TestClient, db: Session) -> None:
    assert client.post("/ai/consulta", json={"pergunta": "Quais PTs?"}).status_code == 401


def test_consulta_sem_chave_responde_503(client: TestClient, cenario: dict) -> None:
    """Sem chave a rota de IA cai sozinha; o resto da aplicação continua de pé."""
    resposta = client.post(
        "/ai/consulta", headers=cenario["cabecalho"], json={"pergunta": "Quais PTs estão abertas?"}
    )

    assert resposta.status_code == 503
    assert "chave" in resposta.json()["detail"]
    assert client.get("/pts", headers=cenario["cabecalho"]).status_code == 200


def test_pergunta_vazia_e_rejeitada(client: TestClient, cenario: dict) -> None:
    resposta = client.post("/ai/consulta", headers=cenario["cabecalho"], json={"pergunta": "?"})

    assert resposta.status_code == 422
