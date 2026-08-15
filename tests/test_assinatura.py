"""Quem assina é quem prova o PIN, e não quem abriu a sessão no aparelho.

O tablet do convés é compartilhado. Se a autoria viesse do token, todas as assinaturas do turno
sairiam no nome de quem destravou a tela de manhã — e a trilha, que existe para dizer quem
autorizou trabalho de risco, registraria uma autoria que não aconteceu.
"""

from collections.abc import Callable
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Anexo, Area, Assinatura, AuditEvent, ModeloPT, PermissaoTrabalho
from app.models import Unidade, Usuario
from app.models.enums import (
    EstadoPT,
    PerfilUsuario,
    TipoAnexo,
    TipoTrabalho,
    TipoUnidade,
)
from app.models.permissao import PTEquipe
from app.models.tipos import agora_utc
from app.security.limite import ASSINATURA
from tests.conftest import PIN_DE_TESTE, assinatura


@pytest.fixture(autouse=True)
def _limite_zerado() -> None:
    """O limitador é estado em processo: sem isto, um teste herda a contagem do anterior."""
    ASSINATURA._marcas.clear()


@pytest.fixture
def cenario(db: Session, criar_usuario: Callable[..., Usuario]) -> dict:
    """PT em VALIDACAO, pronta para a etapa que o responsável de área assina."""
    unidade = Unidade(
        nome="FPSO de teste", identificador_operacional="FPSO-T", tipo=TipoUnidade.FPSO
    )
    db.add(unidade)
    db.flush()
    area = Area(unidade_id=unidade.id, nome="Convés", codigo="CV")
    modelo = ModeloPT(tipo_trabalho=TipoTrabalho.TRABALHO_EM_ALTURA, nome="PT altura", campos=[])
    db.add_all([area, modelo])
    db.commit()

    pessoas = {
        "requisitante": criar_usuario(matricula="70001", unidade_id=unidade.id),
        "area": criar_usuario(
            matricula="70002", perfil=PerfilUsuario.AREA_RESPONSAVEL, unidade_id=unidade.id
        ),
        "coordenador": criar_usuario(
            matricula="70004", perfil=PerfilUsuario.COORDENADOR, unidade_id=unidade.id
        ),
        "executante": criar_usuario(
            matricula="70005", perfil=PerfilUsuario.EXECUTANTE, unidade_id=unidade.id
        ),
    }

    inicio = agora_utc()
    fim = inicio + timedelta(hours=8)
    pt = PermissaoTrabalho(
        numero="PT-2026-0001",
        tipo_trabalho=TipoTrabalho.TRABALHO_EM_ALTURA,
        modelo_pt_id=modelo.id,
        unidade_id=unidade.id,
        area_id=area.id,
        requisitante_id=pessoas["requisitante"].id,
        descricao="Substituição de guarda-corpo",
        valida_de=inicio,
        valida_ate=fim,
        estado=EstadoPT.VALIDACAO,
    )
    db.add(pt)
    db.flush()
    db.add(PTEquipe(pt_id=pt.id, usuario_id=pessoas["executante"].id, funcao="Montador"))
    for tipo in (TipoAnexo.APR, TipoAnexo.ASO):
        db.add(
            Anexo(
                pt_id=pt.id,
                tipo=tipo,
                nome_arquivo=f"{tipo}.pdf",
                caminho=f"/x/{tipo}.pdf",
                hash_sha256="a" * 64,
                valido_ate=fim.date() + timedelta(days=90),
                enviado_por_id=pessoas["requisitante"].id,
            )
        )
    db.commit()
    return {"pt": pt, "pessoas": pessoas, "unidade": unidade}


def _assinar(client: TestClient, pt_id: int, headers: dict, corpo: dict):  # noqa: ANN202
    return client.post(f"/pts/{pt_id}/transicoes", headers=headers, json=corpo)


def test_a_assinatura_sai_no_nome_de_quem_deu_o_pin_e_nao_de_quem_abriu_a_sessao(
    client: TestClient, db: Session, cenario: dict,
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """O caso que dá nome ao recurso: o tablet é de um, a assinatura é de outro."""
    pt = cenario["pt"]
    coordenadora = autenticar("70004")  # quem está com o aparelho na mão

    resposta = _assinar(
        client,
        pt.id,
        coordenadora,
        {"destino": "ANALISE_SMS", **assinatura("70002")},  # quem de fato assina
    )

    assert resposta.status_code == 200, resposta.text
    db.expire_all()

    registrada = db.scalar(select(Assinatura).where(Assinatura.pt_id == pt.id))
    assert registrada.usuario_id == cenario["pessoas"]["area"].id, (
        "a assinatura saiu no nome de quem operava o aparelho"
    )

    evento = db.scalars(
        select(AuditEvent).where(AuditEvent.pt_id == pt.id).order_by(AuditEvent.id.desc())
    ).first()
    assert evento.ator_id == cenario["pessoas"]["area"].id
    assert evento.perfil_ator == PerfilUsuario.AREA_RESPONSAVEL


def test_sem_identificacao_a_etapa_que_assina_e_recusada(
    client: TestClient, db: Session, cenario: dict,
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Token não é autoria: ele vale um turno inteiro e o aparelho passa de mão em mão."""
    pt = cenario["pt"]

    resposta = _assinar(client, pt.id, autenticar("70002"), {"destino": "ANALISE_SMS"})

    assert resposta.status_code == 409
    assert "assinatura_exige_identificacao" in {p["codigo"] for p in resposta.json()["detail"]}
    db.expire_all()
    assert db.get(PermissaoTrabalho, pt.id).estado == EstadoPT.VALIDACAO


@pytest.mark.parametrize(
    "matricula, pin",
    [
        ("70002", "0000"),      # PIN errado
        ("99999", PIN_DE_TESTE),  # matrícula que não existe
    ],
)
def test_credencial_de_assinatura_errada_recusa_sempre_igual(
    client: TestClient, cenario: dict, autenticar: Callable[[str], dict[str, str]],
    matricula: str, pin: str,
) -> None:
    """Uma resposta só para todos os modos de falhar.

    Distinguir "PIN errado" de "matrícula inexistente" diria, a quem tem um crachá na mão, se
    aquela pessoa assina neste sistema.
    """
    resposta = _assinar(
        client,
        cenario["pt"].id,
        autenticar("70002"),
        {"destino": "ANALISE_SMS", "matricula": matricula, "pin": pin},
    )

    assert resposta.status_code == 409
    pendencia = resposta.json()["detail"][0]
    assert pendencia["codigo"] == "assinante_nao_confirmado"
    assert "Matrícula ou PIN" in pendencia["mensagem"]


def test_quem_nao_tem_pin_nao_assina(
    client: TestClient, db: Session, cenario: dict,
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """PIN vazio é o estado de quem existe no sistema mas ainda não recebeu credencial."""
    cenario["pessoas"]["area"].pin_hash = ""
    db.commit()

    resposta = _assinar(
        client,
        cenario["pt"].id,
        autenticar("70002"),
        {"destino": "ANALISE_SMS", **assinatura("70002")},
    )

    assert resposta.status_code == 409
    assert resposta.json()["detail"][0]["codigo"] == "assinante_nao_confirmado"


def test_pin_nao_abre_caminho_por_fora_da_segregacao_de_funcoes(
    client: TestClient, db: Session, cenario: dict,
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Regra 8 continua valendo sobre **quem assina**, e não sobre quem opera.

    Este é o buraco que o PIN poderia abrir se a autoria fosse confirmada e o motor de regras
    continuasse olhando o token: o requisitante daria o próprio PIN e aprovaria a própria PT.
    """
    resposta = _assinar(
        client,
        cenario["pt"].id,
        autenticar("70004"),
        {"destino": "ANALISE_SMS", **assinatura("70001")},  # o requisitante da PT
    )

    assert resposta.status_code == 409
    assert "papel_incompativel_com_o_perfil" in {p["codigo"] for p in resposta.json()["detail"]}
    db.expire_all()
    assert db.get(PermissaoTrabalho, cenario["pt"].id).estado == EstadoPT.VALIDACAO


def test_assinante_de_outra_unidade_nao_alcanca_a_pt(
    client: TestClient, db: Session, cenario: dict,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> None:
    """O PIN não é atalho por fora do escopo (regra 5).

    Sem esta conferência, bastaria abrir a sessão numa unidade para assinar documento de outra
    — coisa que a mesma pessoa não conseguiria nem ler pela API.
    """
    outra = Unidade(
        nome="FPSO Beta", identificador_operacional="FPSO-B", tipo=TipoUnidade.FPSO
    )
    db.add(outra)
    db.flush()
    criar_usuario(
        matricula="70088", perfil=PerfilUsuario.AREA_RESPONSAVEL, unidade_id=outra.id
    )
    db.commit()

    resposta = _assinar(
        client,
        cenario["pt"].id,
        autenticar("70004"),
        {"destino": "ANALISE_SMS", **assinatura("70088")},
    )

    assert resposta.status_code == 409
    assert resposta.json()["detail"][0]["codigo"] == "assinante_fora_do_escopo"


def test_pin_desativado_junto_com_a_conta(
    client: TestClient, db: Session, cenario: dict,
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Desativar alguém precisa tirar a caneta da mão, não só a chave da porta."""
    cenario["pessoas"]["area"].ativo = False
    db.commit()

    resposta = _assinar(
        client,
        cenario["pt"].id,
        autenticar("70004"),
        {"destino": "ANALISE_SMS", **assinatura("70002")},
    )

    assert resposta.status_code == 409
    assert resposta.json()["detail"][0]["codigo"] == "assinante_nao_confirmado"


def test_o_pin_tem_limite_de_tentativas_mais_apertado_que_a_senha(
    client: TestClient, cenario: dict, autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Quatro dígitos são dez mil combinações: sem limite curto, um fim de semana basta."""
    cabecalho = autenticar("70004")
    corpo = {"destino": "ANALISE_SMS", "matricula": "70002", "pin": "0000"}

    for _ in range(3):
        assert _assinar(client, cenario["pt"].id, cabecalho, corpo).status_code == 409

    barrada = _assinar(client, cenario["pt"].id, cabecalho, corpo)

    assert barrada.status_code == 429
    assert "Retry-After" in barrada.headers


def test_o_pin_nao_aparece_em_lugar_nenhum_do_que_e_gravado(
    client: TestClient, db: Session, cenario: dict,
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Credencial que vaza para a trilha vira credencial pública: a trilha é feita para ser lida."""
    pt = cenario["pt"]
    resposta = _assinar(
        client,
        pt.id,
        autenticar("70004"),
        {"destino": "ANALISE_SMS", **assinatura("70002")},
    )
    assert resposta.status_code == 200

    assert PIN_DE_TESTE not in resposta.text
    db.expire_all()
    for evento in db.scalars(select(AuditEvent).where(AuditEvent.pt_id == pt.id)):
        assert PIN_DE_TESTE not in (evento.motivo or "")
        assert PIN_DE_TESTE not in str(evento.dispositivo or "")
    # E o hash guardado nunca é o PIN em texto.
    assinada = db.scalar(select(Assinatura).where(Assinatura.pt_id == pt.id))
    assert PIN_DE_TESTE not in assinada.hash_documento


def test_a_senha_nao_serve_como_pin(
    client: TestClient, cenario: dict, autenticar: Callable[[str], dict[str, str]],
) -> None:
    """São credenciais distintas de propósito, e o código não pode confundi-las.

    Se `identificar_assinante` conferisse contra `senha_hash`, tudo passaria nos outros testes
    e a segunda credencial não existiria de fato.
    """
    from tests.conftest import SENHA_DE_TESTE

    resposta = _assinar(
        client,
        cenario["pt"].id,
        autenticar("70004"),
        {"destino": "ANALISE_SMS", "matricula": "70002", "pin": SENHA_DE_TESTE},
    )

    assert resposta.status_code == 409
    assert resposta.json()["detail"][0]["codigo"] == "assinante_nao_confirmado"


def test_pin_atribuido_pela_coordenacao_nao_assina_ate_ser_trocado(
    client: TestClient, db: Session, cenario: dict,
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """A janela entre entregar e trocar, fechada — e é o que torna a entrega segura.

    Sem esta recusa o recurso teria criado o problema que veio resolver: a coordenação
    atribuiria um PIN, o conheceria, e poderia assinar no nome da pessoa até ela trocá-lo.
    Prendido nos dois sentidos: nem o dono nem quem entregou conseguem assinar antes da troca.
    """
    pt = cenario["pt"]
    area = cenario["pessoas"]["area"]
    coordenadora = autenticar("70004")

    atribuir = client.post(
        f"/usuarios/{area.id}/pin", json={"pin": "8362"}, headers=coordenadora
    )
    assert atribuir.status_code == 204, atribuir.text

    # Quem entregou sabe o PIN e mesmo assim não assina com ele.
    pela_coordenacao = _assinar(
        client, pt.id, coordenadora, {"destino": "ANALISE_SMS", "matricula": "70002", "pin": "8362"}
    )
    assert pela_coordenacao.status_code == 409
    assert pela_coordenacao.json()["detail"][0]["codigo"] == "pin_precisa_troca"

    # E o dono também não, antes de trocar.
    ASSINATURA._marcas.clear()
    pelo_dono = _assinar(
        client, pt.id, autenticar("70002"),
        {"destino": "ANALISE_SMS", "matricula": "70002", "pin": "8362"},
    )
    assert pelo_dono.status_code == 409
    assert pelo_dono.json()["detail"][0]["codigo"] == "pin_precisa_troca"

    db.expire_all()
    assert db.get(PermissaoTrabalho, pt.id).estado == EstadoPT.VALIDACAO


def test_depois_de_trocar_o_pin_atribuido_a_assinatura_volta_a_valer(
    client: TestClient, db: Session, cenario: dict,
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """A prova pelo outro lado: a recusa é da troca pendente, não do PIN novo."""
    pt = cenario["pt"]
    area = cenario["pessoas"]["area"]

    client.post(f"/usuarios/{area.id}/pin", json={"pin": "8362"}, headers=autenticar("70004"))

    ASSINATURA._marcas.clear()
    trocar = client.post(
        "/auth/pin", json={"pin_atual": "8362", "pin_novo": "5074"}, headers=autenticar("70002")
    )
    assert trocar.status_code == 204, trocar.text

    ASSINATURA._marcas.clear()
    resposta = _assinar(
        client, pt.id, autenticar("70004"),
        {"destino": "ANALISE_SMS", "matricula": "70002", "pin": "5074"},
    )

    assert resposta.status_code == 200, resposta.text
    db.expire_all()
    assert db.get(PermissaoTrabalho, pt.id).estado == EstadoPT.ANALISE_SMS
    assert not db.get(Usuario, area.id).pin_precisa_troca


def test_recusa_por_troca_pendente_nao_gasta_o_limite_de_tentativas(
    client: TestClient, cenario: dict, autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Obedecer a mensagem não pode ser o que impede de obedecê-la.

    A rota de troca compartilha este limitador de propósito — é o mesmo segredo. Se cada
    recusa por "troque o PIN" contasse como tentativa, três toques no botão trancariam a troca
    por um minuto e a pessoa ficaria presa entre uma tela que manda trocar e um servidor que
    recusa. Encontrado rodando a aplicação, não pela suíte.
    """
    pt = cenario["pt"]
    area = cenario["pessoas"]["area"]
    coordenadora = autenticar("70004")

    client.post(f"/usuarios/{area.id}/pin", json={"pin": "8362"}, headers=coordenadora)

    corpo = {"destino": "ANALISE_SMS", "matricula": "70002", "pin": "8362"}
    for _ in range(5):
        recusa = _assinar(client, pt.id, coordenadora, corpo)
        assert recusa.status_code == 409, recusa.text
        assert recusa.json()["detail"][0]["codigo"] == "pin_precisa_troca"

    # E a troca continua alcançável depois de todas elas.
    trocou = client.post(
        "/auth/pin", json={"pin_atual": "8362", "pin_novo": "5074"}, headers=autenticar("70002")
    )
    assert trocou.status_code == 204, trocou.text


def test_pin_errado_continua_gastando_o_limite(
    client: TestClient, cenario: dict, autenticar: Callable[[str], dict[str, str]],
) -> None:
    """A prova pelo outro lado: a liberação antecipada vale para quem acertou o segredo.

    Sem este par, a correção acima poderia ter desarmado o limitador para todo mundo e nada
    acusaria.
    """
    pt = cenario["pt"]
    coordenadora = autenticar("70004")
    corpo = {"destino": "ANALISE_SMS", "matricula": "70002", "pin": "0000"}

    for _ in range(3):
        assert _assinar(client, pt.id, coordenadora, corpo).status_code == 409

    excedido = _assinar(client, pt.id, coordenadora, corpo)
    assert excedido.status_code == 429
