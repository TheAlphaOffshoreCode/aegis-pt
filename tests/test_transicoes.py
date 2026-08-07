"""Fluxo de aprovação ponta a ponta: assinatura, versionamento, trilha e os bloqueios."""

from collections.abc import Callable
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Anexo,
    Area,
    Assinatura,
    AuditEvent,
    Certificacao,
    ModeloPT,
    PermissaoTrabalho,
    PTVersao,
    Unidade,
    Usuario,
)
from app.models.enums import (
    EstadoPT,
    PapelAssinatura,
    PerfilUsuario,
    TipoAnexo,
    TipoCertificacao,
    TipoTrabalho,
    TipoUnidade,
)
from app.models.tipos import agora_utc

# Requisitante, área, SMS, coordenação e execução — um por etapa do fluxo.
ELENCO = {
    "requisitante": ("70001", PerfilUsuario.REQUISITANTE),
    "area": ("70002", PerfilUsuario.AREA_RESPONSAVEL),
    "sms": ("70003", PerfilUsuario.TECNICO_SEGURANCA),
    "coordenador": ("70004", PerfilUsuario.COORDENADOR),
    "executante": ("70005", PerfilUsuario.EXECUTANTE),
}


def _montar(
    db: Session,
    criar_usuario: Callable[..., Usuario],
    *,
    certificado_ate: date | None = None,
    com_anexos: bool = True,
) -> dict:
    """PT de trabalho em altura pronta para percorrer o fluxo inteiro."""
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
        papel: criar_usuario(matricula=matricula, perfil=perfil, unidade_id=unidade.id)
        for papel, (matricula, perfil) in ELENCO.items()
    }

    inicio = agora_utc()
    fim = inicio + timedelta(hours=8)
    if certificado_ate is not None:
        db.add(
            Certificacao(
                usuario_id=pessoas["executante"].id,
                tipo=TipoCertificacao.NR_35,
                numero="35-1",
                emitida_em=date(2025, 1, 1),
                valida_ate=certificado_ate,
            )
        )

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
    )
    db.add(pt)
    db.flush()
    from app.models.permissao import PTEquipe

    db.add(PTEquipe(pt_id=pt.id, usuario_id=pessoas["executante"].id, funcao="Montador"))
    if com_anexos:
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
    return {"pt": pt, "pessoas": pessoas}


def _mover(
    client: TestClient, headers: dict, pt_id: int, destino: EstadoPT, motivo: str | None = None
):  # noqa: ANN201
    corpo = {"destino": destino.value}
    if motivo:
        corpo["motivo"] = motivo
    return client.post(f"/pts/{pt_id}/transicoes", json=corpo, headers=headers)


def _codigos(resposta) -> set[str]:  # noqa: ANN001
    return {p["codigo"] for p in resposta.json()["detail"]}


def test_fluxo_completo_ate_execucao(
    client: TestClient, db: Session, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    cenario = _montar(db, criar_usuario, certificado_ate=date.today() + timedelta(days=400))
    pt_id = cenario["pt"].id

    etapas = [
        ("70001", EstadoPT.VALIDACAO),
        ("70002", EstadoPT.ANALISE_SMS),
        ("70003", EstadoPT.APROVACAO),
        ("70004", EstadoPT.LIBERACAO),
        ("70005", EstadoPT.EM_EXECUCAO),
    ]
    for matricula, destino in etapas:
        resposta = _mover(client, autenticar(matricula), pt_id, destino)
        assert resposta.status_code == 200, f"{destino}: {resposta.text}"
        assert resposta.json()["estado"] == destino

    assinaturas = db.scalars(select(Assinatura).where(Assinatura.pt_id == pt_id)).all()
    assert {a.papel for a in assinaturas} == {
        PapelAssinatura.REQUISITANTE,
        PapelAssinatura.AREA_RESPONSAVEL,
        PapelAssinatura.TECNICO_SEGURANCA,
        PapelAssinatura.COORDENADOR,
        PapelAssinatura.EXECUTANTE,
    }
    # Todas assinaram o mesmo documento: o estado não entra no hash.
    assert len({a.hash_documento for a in assinaturas}) == 1
    assert all(a.versao_pt == 1 for a in assinaturas)


def test_certificacao_vencida_impede_a_liberacao(
    client: TestClient, db: Session, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Teste obrigatório: a PT chega até LIBERACAO e para ali."""
    cenario = _montar(db, criar_usuario, certificado_ate=date.today() - timedelta(days=45))
    pt_id = cenario["pt"].id

    for matricula, destino in [
        ("70001", EstadoPT.VALIDACAO),
        ("70002", EstadoPT.ANALISE_SMS),
        ("70003", EstadoPT.APROVACAO),
        ("70004", EstadoPT.LIBERACAO),
    ]:
        assert _mover(client, autenticar(matricula), pt_id, destino).status_code == 200

    barrada = _mover(client, autenticar("70005"), pt_id, EstadoPT.EM_EXECUCAO)

    assert barrada.status_code == 409
    assert "certificacao_vencida" in _codigos(barrada)
    # A sessão do teste tem a PT em cache; quem mudou o estado foi a sessão da requisição.
    db.expire_all()
    assert db.get(PermissaoTrabalho, pt_id).estado == EstadoPT.LIBERACAO


def test_quem_emite_nao_aprova_a_propria_pt(
    client: TestClient, db: Session, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Teste obrigatório: regra 8 valendo pela API, não só no motor."""
    cenario = _montar(db, criar_usuario, certificado_ate=date.today() + timedelta(days=400))
    pt_id = cenario["pt"].id
    dono = autenticar("70001")
    assert _mover(client, dono, pt_id, EstadoPT.VALIDACAO).status_code == 200

    # O próprio requisitante tentando validar a etapa seguinte.
    recusada = _mover(client, dono, pt_id, EstadoPT.ANALISE_SMS)

    assert recusada.status_code == 409
    assert "papel_incompativel_com_o_perfil" in _codigos(recusada)


def test_coordenador_nao_pula_a_analise_de_sms(
    client: TestClient, db: Session, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    cenario = _montar(db, criar_usuario, certificado_ate=date.today() + timedelta(days=400))
    pt_id = cenario["pt"].id
    assert _mover(client, autenticar("70001"), pt_id, EstadoPT.VALIDACAO).status_code == 200

    pulo = _mover(client, autenticar("70004"), pt_id, EstadoPT.LIBERACAO)

    assert pulo.status_code == 409
    assert "transicao_invalida" in _codigos(pulo)


def test_rejeicao_exige_motivo_e_devolve_ao_rascunho_gerando_versao_nova(
    client: TestClient, db: Session, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    cenario = _montar(db, criar_usuario, certificado_ate=date.today() + timedelta(days=400))
    pt_id = cenario["pt"].id
    assert _mover(client, autenticar("70001"), pt_id, EstadoPT.VALIDACAO).status_code == 200

    sem_motivo = _mover(client, autenticar("70002"), pt_id, EstadoPT.REJEITADA)
    assert sem_motivo.status_code == 409
    assert "motivo_obrigatorio" in _codigos(sem_motivo)

    com_motivo = _mover(
        client, autenticar("70002"), pt_id, EstadoPT.REJEITADA, "Falta o plano de resgate"
    )
    assert com_motivo.status_code == 200

    # Devolver ao rascunho é do requisitante, não de quem rejeitou.
    de_terceiro = _mover(client, autenticar("70002"), pt_id, EstadoPT.RASCUNHO)
    assert de_terceiro.status_code == 409

    assert _mover(client, autenticar("70001"), pt_id, EstadoPT.RASCUNHO).status_code == 200
    assert _mover(client, autenticar("70001"), pt_id, EstadoPT.VALIDACAO).status_code == 200

    db.expire_all()
    versoes = db.scalars(select(PTVersao).where(PTVersao.pt_id == pt_id)).all()
    assert [v.versao for v in sorted(versoes, key=lambda v: v.versao)] == [1, 2]
    assert db.get(PermissaoTrabalho, pt_id).versao == 2


def test_transicao_registra_ator_contexto_e_hash_em_cadeia(
    client: TestClient, db: Session, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    """Regra 6: nenhuma transição sem ator, momento, contexto e hash do documento."""
    cenario = _montar(db, criar_usuario, certificado_ate=date.today() + timedelta(days=400))
    pt_id = cenario["pt"].id
    _mover(client, autenticar("70001"), pt_id, EstadoPT.VALIDACAO)
    _mover(client, autenticar("70002"), pt_id, EstadoPT.ANALISE_SMS)

    eventos = db.scalars(
        select(AuditEvent).where(AuditEvent.pt_id == pt_id).order_by(AuditEvent.id)
    ).all()

    assert len(eventos) == 2
    primeiro, segundo = eventos
    assert primeiro.hash_anterior is None
    assert segundo.hash_anterior == primeiro.hash_evento  # a cadeia liga
    assert primeiro.hash_evento != segundo.hash_evento
    for evento in eventos:
        assert evento.ator_id is not None
        assert evento.ocorrido_em is not None
        assert evento.hash_documento is not None
        assert evento.dispositivo is not None  # user-agent do cliente
        assert evento.estado_origem is not None and evento.estado_destino is not None


def test_transicoes_disponiveis_dizem_o_que_este_usuario_pode_fazer(
    client: TestClient, db: Session, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    cenario = _montar(db, criar_usuario, certificado_ate=date.today() + timedelta(days=400))
    pt_id = cenario["pt"].id

    do_dono = client.get(f"/pts/{pt_id}/transicoes", headers=autenticar("70001")).json()
    do_executante = client.get(f"/pts/{pt_id}/transicoes", headers=autenticar("70005")).json()

    assert [t["destino"] for t in do_dono] == [EstadoPT.VALIDACAO]
    assert do_dono[0]["permitida"] is True
    assert do_executante[0]["permitida"] is False  # mesmo passo, outro perfil


def test_pt_em_execucao_e_suspensa_e_retomada(
    client: TestClient, db: Session, criar_usuario: Callable[..., Usuario],
    autenticar: Callable[[str], dict[str, str]],
) -> None:
    cenario = _montar(db, criar_usuario, certificado_ate=date.today() + timedelta(days=400))
    pt_id = cenario["pt"].id
    for matricula, destino in [
        ("70001", EstadoPT.VALIDACAO), ("70002", EstadoPT.ANALISE_SMS),
        ("70003", EstadoPT.APROVACAO), ("70004", EstadoPT.LIBERACAO),
        ("70005", EstadoPT.EM_EXECUCAO),
    ]:
        _mover(client, autenticar(matricula), pt_id, destino)

    suspensa = _mover(
        client, autenticar("70003"), pt_id, EstadoPT.SUSPENSA, "Mudança nas condições de mar"
    )
    assert suspensa.status_code == 200
    assert suspensa.json()["estado"] == EstadoPT.SUSPENSA

    assert _mover(client, autenticar("70004"), pt_id, EstadoPT.EM_EXECUCAO).status_code == 200
