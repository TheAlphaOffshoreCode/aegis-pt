"""Trilha imutável: a cadeia detecta adulteração, e o ORM recusa alterá-la."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.audit.trilha import Contexto, calcular_hash, montar_payload
from app.audit.verificador import verificar_cadeia
from app.models import Area, AuditEvent, ModeloPT, PermissaoTrabalho, Unidade, Usuario
from app.models.auditoria import TrilhaImutavel
from app.models.enums import EstadoPT, PerfilUsuario, TipoTrabalho, TipoUnidade
from app.models.tipos import agora_utc


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
        f"/pts/{pt['id']}/transicoes", headers=cabecalho, json={"destino": "VALIDACAO"}
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
        json={"destino": "REJEITADA", "motivo": "Falta APR"},
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
        json={"destino": "REJEITADA", "motivo": "Refazer a APR"},
    )
    assert rejeicao.status_code == 200, rejeicao.text
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
        },
    )
    assert edicao.status_code == 200, edicao.text

    db.expire_all()
    eventos = _eventos(db, pt.id)
    assert "pt.editada" in [e.tipo_evento for e in eventos]
    assert verificar_cadeia(eventos, pt.uuid) == []
    assert db.get(PermissaoTrabalho, pt.id).estado == EstadoPT.RASCUNHO
