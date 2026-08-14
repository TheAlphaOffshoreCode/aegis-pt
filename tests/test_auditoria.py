"""Trilha imutável: a cadeia detecta adulteração, e o ORM recusa alterá-la."""

import threading
from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.trilha import Contexto, calcular_hash, montar_payload, registrar_evento
from app.audit.verificador import verificar_cadeia
from app.database import SessionLocal, engine
from app.models import Area, AuditEvent, ModeloPT, PermissaoTrabalho, Unidade, Usuario
from app.models.auditoria import TrilhaImutavel
from app.models.enums import EstadoPT, PerfilUsuario, TipoTrabalho, TipoUnidade
from app.models.tipos import agora_utc
from tests.conftest import PIN_DE_TESTE, assinatura


@pytest.fixture
def pt_com_trilha(
    client: TestClient, db: Session,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> dict:
    """PT criada e enviada para validação: dois elos na cadeia."""
    unidade = Unidade(
        nome="FPSO de teste", identificador_operacional="FPSO-T", tipo=TipoUnidade.FPSO
    )
    db.add(unidade)
    db.flush()
    area = Area(unidade_id=unidade.id, nome="Convés", codigo="CV")
    modelo = ModeloPT(tipo_trabalho=TipoTrabalho.TRABALHO_A_QUENTE, nome="PT quente", campos=[])
    db.add_all([area, modelo])
    db.commit()

    criar_usuario(matricula="70001", unidade_id=unidade.id)
    criar_usuario(matricula="70002", perfil=PerfilUsuario.COORDENADOR, unidade_id=unidade.id)
    criar_usuario(
        matricula="70003", perfil=PerfilUsuario.AREA_RESPONSAVEL, unidade_id=unidade.id
    )
    cabecalho = autenticar("70001")

    inicio = agora_utc()
    pt = client.post(
        "/pts",
        headers=cabecalho,
        json={
            "tipo_trabalho": TipoTrabalho.TRABALHO_A_QUENTE.value,
            "modelo_pt_id": modelo.id,
            "unidade_id": unidade.id,
            "area_id": area.id,
            "descricao": "Solda em suporte",
            "valida_de": inicio.isoformat(),
            "valida_ate": (inicio + timedelta(hours=8)).isoformat(),
        },
    ).json()
    client.post(
        f"/pts/{pt['id']}/transicoes",
        headers=cabecalho,
        json={"destino": "VALIDACAO", **assinatura("70001")},
    )
    db.expire_all()
    return {"pt": db.get(PermissaoTrabalho, pt["id"]), "cabecalho": cabecalho}


def _eventos(db: Session, pt_id: int) -> list[AuditEvent]:
    return list(
        db.scalars(select(AuditEvent).where(AuditEvent.pt_id == pt_id).order_by(AuditEvent.id))
    )


def test_a_trilha_comeca_no_nascimento_da_pt(pt_com_trilha: dict, db: Session) -> None:
    """A criação é o primeiro elo: sem ela, a origem do documento ficaria fora da cadeia."""
    eventos = _eventos(db, pt_com_trilha["pt"].id)

    assert [e.tipo_evento for e in eventos] == ["pt.criada", "pt.transicao.validacao"]
    assert eventos[0].hash_anterior is None
    assert eventos[1].hash_anterior == eventos[0].hash_evento


def test_cadeia_intacta_nao_acusa_nada(pt_com_trilha: dict, db: Session) -> None:
    pt = pt_com_trilha["pt"]
    assert verificar_cadeia(_eventos(db, pt.id), pt.uuid) == []


def test_alterar_o_conteudo_de_um_evento_quebra_a_cadeia(
    pt_com_trilha: dict, db: Session
) -> None:
    """Teste obrigatório do contrato: adulteração é detectada.

    A alteração é feita por SQL direto, que é o cenário real — alguém com acesso ao banco,
    contornando a aplicação inteira.
    """
    pt = pt_com_trilha["pt"]
    primeiro = _eventos(db, pt.id)[0]

    db.execute(
        text("UPDATE audit_event SET motivo = :m WHERE id = :i"),
        {"m": "motivo reescrito depois do fato", "i": primeiro.id},
    )
    db.commit()
    db.expire_all()

    quebras = verificar_cadeia(_eventos(db, pt.id), pt.uuid)

    assert quebras, "a adulteração passou despercebida"
    assert quebras[0].evento_id == primeiro.id
    assert "conteúdo" in quebras[0].motivo


def test_apagar_um_evento_do_meio_quebra_o_elo(
    client: TestClient, pt_com_trilha: dict, db: Session,
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    pt = pt_com_trilha["pt"]
    rejeicao = client.post(
        f"/pts/{pt.id}/transicoes",
        headers=autenticar("70003"),  # responsável de área é quem rejeita nesta etapa
        json={"destino": "REJEITADA", "motivo": "Falta APR", **assinatura("70003")},
    )
    assert rejeicao.status_code == 200, rejeicao.text
    db.expire_all()
    do_meio = _eventos(db, pt.id)[1]

    db.execute(text("DELETE FROM audit_event WHERE id = :i"), {"i": do_meio.id})
    db.commit()
    db.expire_all()

    quebras = verificar_cadeia(_eventos(db, pt.id), pt.uuid)

    assert quebras
    assert "elo anterior" in quebras[0].motivo


def test_trocar_o_hash_registrado_tambem_e_detectado(pt_com_trilha: dict, db: Session) -> None:
    pt = pt_com_trilha["pt"]
    alvo = _eventos(db, pt.id)[0]

    db.execute(
        text("UPDATE audit_event SET hash_evento = :h WHERE id = :i"),
        {"h": "f" * 64, "i": alvo.id},
    )
    db.commit()
    db.expire_all()

    assert verificar_cadeia(_eventos(db, pt.id), pt.uuid)


def test_evento_selado_num_formato_antigo_continua_conferindo(
    pt_com_trilha: dict, db: Session
) -> None:
    """Acrescentar campo ao payload não pode invalidar a trilha já selada.

    Sem a versão de formato, o `evento_compensado_id` que entrou no payload no L6 teria
    quebrado retroativamente todos os eventos gravados no L5.
    """
    pt = pt_com_trilha["pt"]
    ultimo = _eventos(db, pt.id)[-1]
    ocorrido_em = agora_utc()

    payload_v1 = montar_payload(
        versao=1,
        pt_uuid=pt.uuid,
        tipo_evento="pt.legado",
        ator_id=None,
        estado_origem=None,
        estado_destino=None,
        motivo="gravado antes do formato mudar",
        ocorrido_em=ocorrido_em,
        hash_documento=None,
        contexto=Contexto(),
    )
    db.add(
        AuditEvent(
            pt_id=pt.id,
            tipo_evento="pt.legado",
            motivo="gravado antes do formato mudar",
            ocorrido_em=ocorrido_em,
            hash_anterior=ultimo.hash_evento,
            hash_evento=calcular_hash(ultimo.hash_evento, payload_v1),
            versao_payload=1,
        )
    )
    db.commit()
    db.expire_all()

    assert verificar_cadeia(_eventos(db, pt.id), pt.uuid) == []


def test_trocar_a_versao_de_formato_de_um_evento_e_detectado(
    pt_com_trilha: dict, db: Session
) -> None:
    """A versão não é uma etiqueta livre: mudá-la muda como o hash é conferido."""
    pt = pt_com_trilha["pt"]
    alvo = _eventos(db, pt.id)[0]

    db.execute(
        text("UPDATE audit_event SET versao_payload = 1 WHERE id = :i"), {"i": alvo.id}
    )
    db.commit()
    db.expire_all()

    assert verificar_cadeia(_eventos(db, pt.id), pt.uuid)


@pytest.mark.parametrize("operacao", ["alterar", "apagar"])
def test_o_orm_recusa_alterar_ou_apagar_um_evento(
    pt_com_trilha: dict, db: Session, operacao: str
) -> None:
    """Regra 4 provada: append-only não depende de todo mundo lembrar."""
    evento = _eventos(db, pt_com_trilha["pt"].id)[0]

    if operacao == "alterar":
        evento.motivo = "outro motivo"
    else:
        db.delete(evento)

    with pytest.raises(TrilhaImutavel):
        db.commit()
    db.rollback()


def test_endpoint_de_trilha_conferre_e_respeita_o_escopo(
    client: TestClient, pt_com_trilha: dict,
    criar_usuario: Callable[..., Usuario], autenticar: Callable[[str], dict[str, str]],
) -> None:
    pt = pt_com_trilha["pt"]

    corpo = client.get(f"/pts/{pt.id}/trilha", headers=pt_com_trilha["cabecalho"]).json()

    assert corpo["integra"] is True
    assert corpo["quebras"] == []
    assert len(corpo["eventos"]) == 2
    assert all(e["hash_evento"] for e in corpo["eventos"])

    criar_usuario(matricula="70009", unidade_id=None)  # sem lotação: não alcança nada
    de_fora = client.get(f"/pts/{pt.id}/trilha", headers=autenticar("70009"))
    assert de_fora.status_code == 404


def test_compensacao_cria_evento_novo_sem_tocar_no_original(
    client: TestClient, pt_com_trilha: dict, db: Session,
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Regra 4: corrigir é acrescentar, nunca reescrever."""
    pt = pt_com_trilha["pt"]
    original = _eventos(db, pt.id)[0]
    motivo_antes = original.motivo
    hash_antes = original.hash_evento

    resposta = client.post(
        f"/pts/{pt.id}/trilha/{original.id}/compensacao",
        headers=autenticar("70002"),  # coordenador
        json={"motivo": "Registro anterior apontava a área errada"},
    )

    assert resposta.status_code == 201
    assert resposta.json()["evento_compensado_id"] == original.id

    db.expire_all()
    eventos = _eventos(db, pt.id)
    assert len(eventos) == 3
    assert eventos[0].motivo == motivo_antes  # o original segue lá, intocado
    assert eventos[0].hash_evento == hash_antes
    assert verificar_cadeia(eventos, pt.uuid) == []  # e a cadeia continua fechando


def test_compensacao_recusa_evento_de_outra_pt_ou_de_outra_compensacao(
    client: TestClient, pt_com_trilha: dict, db: Session,
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    pt = pt_com_trilha["pt"]
    cabecalho = autenticar("70002")
    original = _eventos(db, pt.id)[0]

    inexistente = client.post(
        f"/pts/{pt.id}/trilha/9999/compensacao", headers=cabecalho, json={"motivo": "x"}
    )
    assert inexistente.status_code == 409
    assert {p["codigo"] for p in inexistente.json()["detail"]} == {"evento_inexistente"}

    compensacao_id = client.post(
        f"/pts/{pt.id}/trilha/{original.id}/compensacao",
        headers=cabecalho,
        json={"motivo": "Correção"},
    ).json()["id"]

    em_cadeia = client.post(
        f"/pts/{pt.id}/trilha/{compensacao_id}/compensacao",
        headers=cabecalho,
        json={"motivo": "Corrigindo a correção"},
    )
    assert em_cadeia.status_code == 409
    assert {p["codigo"] for p in em_cadeia.json()["detail"]} == {"compensacao_de_compensacao"}


def test_requisitante_nao_compensa_a_trilha(
    client: TestClient, pt_com_trilha: dict, db: Session
) -> None:
    original = _eventos(db, pt_com_trilha["pt"].id)[0]

    resposta = client.post(
        f"/pts/{pt_com_trilha['pt'].id}/trilha/{original.id}/compensacao",
        headers=pt_com_trilha["cabecalho"],
        json={"motivo": "quero corrigir"},
    )

    assert resposta.status_code == 403


def test_editar_rascunho_deixa_rastro(
    client: TestClient, pt_com_trilha: dict, db: Session, autenticar: Callable[[str], dict]
) -> None:
    pt = pt_com_trilha["pt"]
    rejeicao = client.post(
        f"/pts/{pt.id}/transicoes",
        headers=autenticar("70003"),
        json={"destino": "REJEITADA", "motivo": "Refazer a APR", "matricula": "70003", "pin": PIN_DE_TESTE},
    )
    assert rejeicao.status_code == 200, rejeicao.text
    # Sem credencial de assinatura de propósito: devolver ao rascunho é ato administrativo,
    # não assina, e por isso o serviço não exige PIN. É o outro lado da regra.
    volta = client.post(
        f"/pts/{pt.id}/transicoes",
        headers=pt_com_trilha["cabecalho"],
        json={"destino": "RASCUNHO"},
    )
    assert volta.status_code == 200, volta.text

    db.expire_all()
    atual = db.get(PermissaoTrabalho, pt.id)
    edicao = client.patch(
        f"/pts/{pt.id}",
        headers=pt_com_trilha["cabecalho"],
        json={
            "tipo_trabalho": atual.tipo_trabalho.value,
            "modelo_pt_id": atual.modelo_pt_id,
            "area_id": atual.area_id,
            "descricao": "Solda em suporte — descrição corrigida",
            "valida_de": atual.valida_de.isoformat(),
            "valida_ate": atual.valida_ate.isoformat(),
            "visto_em": atual.atualizado_em.isoformat(),
        },
    )
    assert edicao.status_code == 200, edicao.text

    db.expire_all()
    eventos = _eventos(db, pt.id)
    assert "pt.editada" in [e.tipo_evento for e in eventos]
    assert verificar_cadeia(eventos, pt.uuid) == []
    assert db.get(PermissaoTrabalho, pt.id).estado == EstadoPT.RASCUNHO


def test_banco_recusa_dois_eventos_encadeados_no_mesmo_elo(
    pt_com_trilha: dict, db: Session
) -> None:
    """Um elo só pode ter um sucessor — a restrição, e não a boa vontade do chamador.

    `registrar_evento` lê o último elo e depois insere. Duas requisições simultâneas na mesma PT
    leem o mesmo `hash_anterior` e nascem irmãs; a cadeia bifurca e o verificador passa a acusar
    adulteração para sempre numa trilha que ninguém tocou. Aqui as duas irmãs são inseridas de
    uma vez, que é o estado exato que a corrida deixaria na tabela.

    A corrida em si não dá para encenar no SQLite, que serializa escritores pela trava do
    arquivo — é justamente por isso que o defeito só apareceria no PostgreSQL de produção. A
    restrição vale nos dois.
    """
    pt = pt_com_trilha["pt"]
    ultimo = _eventos(db, pt.id)[-1]

    def irmao(tipo: str) -> AuditEvent:
        return AuditEvent(
            pt_id=pt.id,
            tipo_evento=tipo,
            ocorrido_em=agora_utc(),
            hash_documento="h",
            hash_anterior=ultimo.hash_evento,
            # Hashes de evento diferentes de propósito: iguais, quem recusaria seria o `unique`
            # de `hash_evento` e o teste passaria sem provar nada sobre o elo.
            hash_evento=calcular_hash(ultimo.hash_evento, tipo),
        )

    db.add_all([irmao("pt.teste.a"), irmao("pt.teste.b")])
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

    assert verificar_cadeia(_eventos(db, pt.id), pt.uuid) == []


@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="O SQLite serializa escritores pela trava do arquivo: a corrida não acontece lá.",
)
def test_dois_escritores_simultaneos_nao_bifurcam_a_cadeia(
    pt_com_trilha: dict, db: Session
) -> None:
    """A corrida encenada de verdade, com duas conexões disputando o mesmo elo.

    O teste acima insere as duas irmãs de uma vez, que é o *estado* que a corrida deixaria. Este
    encena a corrida em si — o que só o PostgreSQL permite, e é por isso que a P49 passou de L4 a
    L13 corrigida no papel e nunca exercitada onde o defeito existe.

    `REPEATABLE READ` é o que torna determinístico: as duas transações abrem o snapshot antes da
    barreira, então ambas leem o mesmo último elo mesmo que uma commite primeiro — exatamente o
    que duas requisições simultâneas fazem sem combinar nada.
    """
    pt_id = pt_com_trilha["pt"].id
    db.commit()  # as outras conexões só enxergam a trilha depois disto

    partida = threading.Barrier(2)
    desfechos: list[str] = []
    trava = threading.Lock()

    def escrever(tipo: str) -> None:
        sessao = SessionLocal()
        # Snapshot congelado no primeiro statement, que é o `get` logo abaixo.
        sessao.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        try:
            pt = sessao.get(PermissaoTrabalho, pt_id)
            partida.wait(timeout=15)
            registrar_evento(
                sessao, pt=pt, tipo_evento=tipo, ator=None, hash_documento="h"
            )
            sessao.commit()
            resultado = "gravou"
        except IntegrityError:
            sessao.rollback()
            resultado = "recusado"
        finally:
            sessao.close()
        with trava:
            desfechos.append(resultado)

    fios = [
        threading.Thread(target=escrever, args=(tipo,))
        for tipo in ("pt.corrida.a", "pt.corrida.b")
    ]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join(timeout=30)
        assert not fio.is_alive(), "escritor travou — a restrição não deve bloquear para sempre"

    # Um grava, o outro leva IntegrityError. Os dois gravando seria a bifurcação.
    assert sorted(desfechos) == ["gravou", "recusado"]

    db.expire_all()
    eventos = _eventos(db, pt_id)
    assert len(eventos) == 3
    assert verificar_cadeia(eventos, pt_com_trilha["pt"].uuid) == []
